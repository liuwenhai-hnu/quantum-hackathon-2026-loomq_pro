#!/usr/bin/env python3
"""Thin LoomQ product service: static frontend plus real L2 generation API."""

from __future__ import annotations

import argparse
import cmath
import importlib.util
import json
import math
import os
import secrets
import sys
import threading
import time
from http.cookies import SimpleCookie
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = ROOT / "frontend"
STARTER_KIT_DIR = ROOT

if str(STARTER_KIT_DIR) not in sys.path:
    sys.path.insert(0, str(STARTER_KIT_DIR))

import adapter  # noqa: E402
from l1.ir import Gate, Measurement  # noqa: E402
from l1.gates import parse_angle  # noqa: E402
from l1.parser import parse_qasm2  # noqa: E402
from l2.backend_requirements import extract_backend_requirements  # noqa: E402
from l2.backend_tool import load_backend_capabilities  # noqa: E402
from l2.backend_verifier import find_matching_backends  # noqa: E402
from l2.client import (  # noqa: E402
    call_llm,
    reset_runtime_llm_config,
    set_runtime_llm_config,
)


MAX_REQUEST_BYTES = 64 * 1024
MAX_TRACE_QUBITS = 5
MAX_TRACE_BASIS_STATES = 8
TRACE_EPSILON = 1e-9
SESSION_COOKIE_NAME = "loomq_session"
LLM_TEST_TIMEOUT_SECONDS = 20


def get_environment_llm_config() -> dict[str, str] | None:
    """Return a complete server LLM config without exposing it to session storage."""
    config = {
        "base_url": os.environ.get("LOOMQ_LLM_BASE_URL", "").strip(),
        "api_key": os.environ.get("LOOMQ_LLM_API_KEY", "").strip(),
        "model": os.environ.get("LOOMQ_LLM_MODEL", "").strip(),
    }
    return config if all(config.values()) else None


class SessionStore:
    """Process-local session storage; API keys never leave server memory."""

    def __init__(self) -> None:
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def ensure(self, candidate: str | None) -> tuple[str, bool]:
        with self._lock:
            if candidate and candidate in self._sessions:
                return candidate, False
            session_id = secrets.token_urlsafe(32)
            self._sessions[session_id] = {
                "config": None,
                "pending": None,
                "connected": False,
            }
            return session_id, True

    def status(
        self,
        session_id: str,
        environment_config: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            session = self._sessions[session_id]
            config = session["config"]
            if config is None and environment_config is not None:
                return {
                    "configured": True,
                    "connected": True,
                    "base_url": environment_config["base_url"],
                    "model": environment_config["model"],
                    "has_api_key": True,
                    "source": "environment",
                }
            return {
                "configured": config is not None,
                "connected": bool(config and session["connected"]),
                "base_url": config["base_url"] if config else "",
                "model": config["model"] if config else "",
                "has_api_key": bool(config and config["api_key"]),
                "source": "session" if config else "none",
            }

    def active_config(self, session_id: str) -> dict[str, str] | None:
        with self._lock:
            config = self._sessions[session_id]["config"]
            return dict(config) if config else None

    def set_pending(self, session_id: str, config: dict[str, str]) -> None:
        with self._lock:
            self._sessions[session_id]["pending"] = dict(config)

    def clear_pending(self, session_id: str) -> None:
        with self._lock:
            self._sessions[session_id]["pending"] = None

    def apply_pending(self, session_id: str) -> dict[str, str] | None:
        with self._lock:
            session = self._sessions[session_id]
            if not session["pending"]:
                return None
            session["config"] = dict(session["pending"])
            session["pending"] = None
            session["connected"] = True
            return dict(session["config"])

    def set_connected(self, session_id: str, connected: bool) -> None:
        with self._lock:
            self._sessions[session_id]["connected"] = connected


SESSION_STORE = SessionStore()

LOCAL_BACKEND_TARGETS = {
    "spinq_taurus_simulator": "spinq",
    "originq_local_simulator": "originq",
    "braket_local_simulator": "braket",
}

BACKEND_RUNTIME_IMPORTS = {
    "spinq_taurus_simulator": ("spinqit",),
    "originq_local_simulator": ("pyqpanda",),
    "braket_local_simulator": ("braket", "braket.devices", "braket.ir.openqasm"),
}

BACKEND_RUNTIME_MESSAGES = {
    "spinq_taurus_simulator": "当前 Python 环境未安装 SpinQ Taurus 本地模拟器依赖。",
    "originq_local_simulator": "当前 Python 环境未安装 OriginQ CPUQVM 本地模拟器依赖。",
    "braket_local_simulator": "当前 Python 环境未安装 AWS Braket 本地模拟器依赖。",
}

BACKEND_LABELS = {
    "kind": {"simulator": "本地模拟器", "qpu": "量子真机", "cloud": "云端服务"},
    "queue": {"none": "无需排队", "minutes_to_hours": "数分钟至数小时", "hours": "数小时"},
    "cost": {"free": "免费", "free_quota": "免费额度", "paid": "付费"},
}

GATE_NAMES = {
    "h": "Hadamard 门",
    "x": "X 门",
    "s": "S 相位门",
    "sdg": "S† 反相位门",
    "t": "T 相位门",
    "tdg": "T† 反相位门",
    "ry": "RY 旋转门",
    "rz": "RZ 旋转门",
    "cx": "CX 受控非门",
    "cu1": "CU1 受控相位门",
    "swap": "SWAP 交换门",
    "ccx": "CCX Toffoli 门",
}

GATE_PURPOSES = {
    "h": "同时保留两种可能，为后续干涉或关联做准备",
    "x": "把这个量子比特从 0 翻到 1，准备需要的输入",
    "s": "给其中一种可能加上相位差",
    "sdg": "撤回一部分相位变化",
    "t": "加入更细小的相位差",
    "tdg": "反向调整一个较小的相位差",
    "ry": "按指定角度重新分配测到 0 和 1 的可能性",
    "rz": "改变两种可能之间的相位关系",
    "cx": "让一个比特的选择影响另一个比特",
    "cu1": "只在控制条件满足时加入相位差",
    "swap": "交换两个量子比特承载的信息",
    "ccx": "只有两个控制条件都满足时才翻转目标比特",
}

GATE_RULES = {
    "h": "把一个确定基态展开成带正负关系的叠加，让后续操作能够产生干涉。叠加并不等于量子比特已经偷偷选好了两个经典值。",
    "x": "交换 |0⟩ 和 |1⟩：|0⟩ → |1⟩，|1⟩ → |0⟩。",
    "s": "只给 |1⟩ 分量乘上 i，改变相位但不直接改变本次测到 0/1 的概率。",
    "sdg": "S 门的逆操作：撤回 S 加入的 π/2 相位。",
    "t": "只给 |1⟩ 分量加入 π/4 相位，为后续干涉留下更细的相位差。",
    "tdg": "T 门的逆操作：给 |1⟩ 分量加入 -π/4 相位。",
    "ry": "让量子态绕 Y 轴旋转 θ；旋转角度决定测到 0 和 1 的概率怎样重新分配。",
    "rz": "让 |0⟩ 与 |1⟩ 分量积累相反方向的相位；单独测量通常看不出，需由后续干涉显现。",
    "cx": "看控制位：控制位是 0 时目标位不变；控制位是 1 时目标位翻转。规则写作 |c,t⟩ → |c,t⊕c⟩。",
    "cu1": "只有控制位和目标位都为 1 的 |11⟩ 分量会获得相位 e^{iθ}，其他基态分量不变。",
    "swap": "交换两个量子比特承载的状态：|a,b⟩ → |b,a⟩，例如 |01⟩ → |10⟩。",
    "ccx": "只有两个控制位都是 1 时才翻转目标位；例如 |110⟩ → |111⟩。其他控制组合保持目标位不变。",
}

GATE_MATH = {
    "h": {"kind": "matrix", "symbol": "H", "coefficient": "1/√2", "rows": [["1", "1"], ["1", "−1"]], "notes": ["H|0⟩ = (|0⟩ + |1⟩)/√2", "H|1⟩ = (|0⟩ − |1⟩)/√2"]},
    "x": {"kind": "matrix", "symbol": "X", "rows": [["0", "1"], ["1", "0"]], "notes": ["X|0⟩ = |1⟩", "X|1⟩ = |0⟩"]},
    "s": {"kind": "matrix", "symbol": "S", "rows": [["1", "0"], ["0", "i"]]},
    "sdg": {"kind": "matrix", "symbol": "S†", "rows": [["1", "0"], ["0", "−i"]]},
    "t": {"kind": "matrix", "symbol": "T", "rows": [["1", "0"], ["0", "e^(iπ/4)"]]},
    "tdg": {"kind": "matrix", "symbol": "T†", "rows": [["1", "0"], ["0", "e^(−iπ/4)"]]},
    "ry": {"kind": "matrix", "symbol": "RY(θ)", "rows": [["cos(θ/2)", "−sin(θ/2)"], ["sin(θ/2)", "cos(θ/2)"]]},
    "rz": {"kind": "matrix", "symbol": "RZ(θ)", "rows": [["e^(−iθ/2)", "0"], ["0", "e^(iθ/2)"]]},
    "cx": {"kind": "rule", "lines": ["|c,t⟩ → |c,t⊕c⟩", "控制位 c=0 时目标位不变；c=1 时目标位翻转。"]},
    "cu1": {"kind": "rule", "lines": ["|11⟩ → e^(iθ)|11⟩", "其余基态分量不变。"]},
    "swap": {"kind": "rule", "lines": ["|a,b⟩ → |b,a⟩", "例如：|01⟩ → |10⟩"]},
    "ccx": {"kind": "rule", "lines": ["|a,b,t⟩ → |a,b,t⊕(a·b)⟩", "仅当 a=b=1 时翻转目标位 t。"]},
}


def format_ket(bits: list[str]) -> str:
    return f"|{''.join(bits)}⟩"


def infer_basis_before(
    operation_index: int,
    operations: list[Gate | Measurement],
    num_qubits: int,
) -> list[str] | None:
    """Track only prefixes that provably stay in one computational basis state."""
    bits = ["0"] * num_qubits
    phase_only = {"s", "sdg", "t", "tdg", "rz", "cu1"}
    for prior in operations[:operation_index]:
        if isinstance(prior, Measurement):
            return None
        name = prior.name.lower()
        qubits = prior.qubit_indices
        if name == "x":
            bits[qubits[0]] = "1" if bits[qubits[0]] == "0" else "0"
        elif name == "cx":
            if bits[qubits[0]] == "1":
                bits[qubits[1]] = "1" if bits[qubits[1]] == "0" else "0"
        elif name == "swap":
            bits[qubits[0]], bits[qubits[1]] = bits[qubits[1]], bits[qubits[0]]
        elif name == "ccx":
            if bits[qubits[0]] == bits[qubits[1]] == "1":
                bits[qubits[2]] = "1" if bits[qubits[2]] == "0" else "0"
        elif name in phase_only:
            continue
        else:
            return None
    return bits


def is_standard_bell_prefix(operations: list[Gate | Measurement]) -> bool:
    gates = [operation for operation in operations if isinstance(operation, Gate)]
    return (
        len(gates) == 2
        and gates[0].name.lower() == "h"
        and gates[1].name.lower() == "cx"
        and gates[1].qubit_indices[0] == gates[0].qubit_indices[0]
    )


def gate_math(operation: Gate | Measurement) -> dict[str, Any]:
    if isinstance(operation, Measurement):
        return {
            "label": "数学形式（测量规则）",
            "kind": "rule",
            "lines": [
                "若 |ψ⟩ = α|0⟩ + β|1⟩，测得 0 的概率为 |α|²，测得 1 的概率为 |β|²。",
                "测量不是普通的可逆矩阵操作。",
            ],
        }
    name = operation.name.lower()
    content = dict(GATE_MATH[name])
    content["label"] = "数学形式"
    if operation.parameter:
        content["parameter"] = operation.parameter
    return content


def qubit_mask(qubit: int, num_qubits: int) -> int:
    """Use the UI's ket order: q0 is the left-most bit."""
    return 1 << (num_qubits - qubit - 1)


def apply_single_qubit_gate(
    state: list[complex],
    qubit: int,
    matrix: tuple[tuple[complex, complex], tuple[complex, complex]],
    num_qubits: int,
) -> list[complex]:
    mask = qubit_mask(qubit, num_qubits)
    result = state.copy()
    for basis in range(len(state)):
        if basis & mask:
            continue
        paired = basis | mask
        zero_amplitude = state[basis]
        one_amplitude = state[paired]
        result[basis] = matrix[0][0] * zero_amplitude + matrix[0][1] * one_amplitude
        result[paired] = matrix[1][0] * zero_amplitude + matrix[1][1] * one_amplitude
    return result


def apply_gate_to_state(state: list[complex], operation: Gate, num_qubits: int) -> list[complex]:
    name = operation.name.lower()
    qubits = operation.qubit_indices
    inverse_sqrt_two = 1 / math.sqrt(2)

    single_qubit_matrices = {
        "h": ((inverse_sqrt_two, inverse_sqrt_two), (inverse_sqrt_two, -inverse_sqrt_two)),
        "x": ((0, 1), (1, 0)),
        "s": ((1, 0), (0, 1j)),
        "sdg": ((1, 0), (0, -1j)),
        "t": ((1, 0), (0, cmath.exp(1j * math.pi / 4))),
        "tdg": ((1, 0), (0, cmath.exp(-1j * math.pi / 4))),
    }
    if name in single_qubit_matrices:
        return apply_single_qubit_gate(state, qubits[0], single_qubit_matrices[name], num_qubits)

    if name in {"ry", "rz"}:
        angle = parse_angle(operation.parameter or "0")
        if name == "ry":
            matrix = (
                (math.cos(angle / 2), -math.sin(angle / 2)),
                (math.sin(angle / 2), math.cos(angle / 2)),
            )
        else:
            matrix = (
                (cmath.exp(-1j * angle / 2), 0),
                (0, cmath.exp(1j * angle / 2)),
            )
        return apply_single_qubit_gate(state, qubits[0], matrix, num_qubits)

    result = [0j] * len(state)
    if name == "cu1":
        angle = parse_angle(operation.parameter or "0")
        control_mask = qubit_mask(qubits[0], num_qubits)
        target_mask = qubit_mask(qubits[1], num_qubits)
        phase = cmath.exp(1j * angle)
        return [
            amplitude * phase if basis & control_mask and basis & target_mask else amplitude
            for basis, amplitude in enumerate(state)
        ]

    for basis, amplitude in enumerate(state):
        mapped = basis
        if name == "cx":
            if basis & qubit_mask(qubits[0], num_qubits):
                mapped ^= qubit_mask(qubits[1], num_qubits)
        elif name == "swap":
            first_mask = qubit_mask(qubits[0], num_qubits)
            second_mask = qubit_mask(qubits[1], num_qubits)
            if bool(basis & first_mask) != bool(basis & second_mask):
                mapped ^= first_mask | second_mask
        elif name == "ccx":
            if basis & qubit_mask(qubits[0], num_qubits) and basis & qubit_mask(qubits[1], num_qubits):
                mapped ^= qubit_mask(qubits[2], num_qubits)
        else:
            raise ValueError(f"Unsupported state trace gate: {name}")
        result[mapped] += amplitude
    return result


def format_number(value: float) -> str:
    if abs(value) < TRACE_EPSILON:
        return "0"
    rounded = round(value, 4)
    return str(int(rounded)) if float(rounded).is_integer() else f"{rounded:g}"


def format_unit_phase(value: complex) -> str:
    candidates = (
        (1, ""),
        (-1, "−"),
        (1j, "i"),
        (-1j, "−i"),
        (cmath.exp(1j * math.pi / 4), "e^(iπ/4)"),
        (cmath.exp(-1j * math.pi / 4), "e^(−iπ/4)"),
        (cmath.exp(3j * math.pi / 4), "e^(i3π/4)"),
        (cmath.exp(-3j * math.pi / 4), "e^(−i3π/4)"),
    )
    for candidate, label in candidates:
        if abs(value - candidate) < TRACE_EPSILON:
            return label
    real = format_number(value.real)
    imaginary = format_number(abs(value.imag))
    if abs(value.imag) < TRACE_EPSILON:
        return real
    if abs(value.real) < TRACE_EPSILON:
        return ("−" if value.imag < 0 else "") + imaginary + "i"
    return f"({real}{'−' if value.imag < 0 else '+'}{imaginary}i)"


def join_state_terms(terms: list[tuple[str, str]]) -> str:
    rendered = ""
    for index, (coefficient, ket) in enumerate(terms):
        negative = coefficient.startswith("−")
        body = coefficient[1:] if negative else coefficient
        term = f"{body}{ket}" if body else ket
        if index == 0:
            rendered = ("−" if negative else "") + term
        else:
            rendered += (" − " if negative else " + ") + term
    return rendered


def format_statevector(state: list[complex], num_qubits: int) -> tuple[str, list[str]]:
    active = [
        (basis, amplitude)
        for basis, amplitude in enumerate(state)
        if abs(amplitude) > TRACE_EPSILON
    ]
    basis_states = [format(basis, f"0{num_qubits}b") for basis, _ in active]
    if len(active) == 1:
        return f"|{basis_states[0]}⟩", basis_states
    magnitudes = [abs(amplitude) for _, amplitude in active]
    uniform = len(active) > 1 and all(abs(magnitude - 1 / math.sqrt(len(active))) < 1e-8 for magnitude in magnitudes)

    if uniform:
        terms = [
            (format_unit_phase(amplitude / abs(amplitude)), f"|{bits}⟩")
            for bits, (_, amplitude) in zip(basis_states, active)
        ]
        return f"({join_state_terms(terms)}) / √{len(active)}", basis_states

    terms = []
    for bits, (_, amplitude) in zip(basis_states, active):
        coefficient = format_unit_phase(amplitude) if abs(abs(amplitude) - 1) < TRACE_EPSILON else format_unit_phase(amplitude)
        terms.append((coefficient, f"|{bits}⟩"))
    return join_state_terms(terms), basis_states


def describe_basis_states(bits_values: list[str]) -> list[str]:
    return [
        f"|{bits}⟩ = " + ", ".join(f"q{index}={bit}" for index, bit in enumerate(bits))
        for bits in dict.fromkeys(bits_values)
    ]


def probabilities_unchanged(before: list[complex], after: list[complex]) -> bool:
    return all(abs(abs(left) ** 2 - abs(right) ** 2) < 1e-8 for left, right in zip(before, after))


def cx_basis_mapping(state: list[complex], operation: Gate, num_qubits: int) -> str:
    control, target = operation.qubit_indices
    mappings = []
    for basis, amplitude in enumerate(state):
        if abs(amplitude) <= TRACE_EPSILON:
            continue
        mapped = basis
        if basis & qubit_mask(control, num_qubits):
            mapped ^= qubit_mask(target, num_qubits)
        mappings.append(f"|{format(basis, f'0{num_qubits}b')}⟩ → |{format(mapped, f'0{num_qubits}b')}⟩")
    return "；".join(mappings)


def is_recombining_h(
    operation: Gate,
    operation_index: int,
    operations: list[Gate | Measurement],
    experiment_kind: str,
) -> bool:
    if operation.name.lower() != "h" or experiment_kind not in {"qft", "phase_interference"}:
        return False
    phase_gates = {"s", "sdg", "t", "tdg", "rz", "cu1"}
    return any(
        isinstance(item, Gate) and item.name.lower() in phase_gates
        for item in operations[:operation_index]
    )


def trace_title(
    operation: Gate,
    operation_index: int,
    operations: list[Gate | Measurement],
    experiment_kind: str,
) -> str:
    name = operation.name.lower()
    if name == "h":
        return (
            "让不同路径重新相遇并发生干涉"
            if is_recombining_h(operation, operation_index, operations, experiment_kind)
            else "制造可以发生干涉的多种路径"
        )
    return {
        "x": "把当前比特翻到另一种状态",
        "s": "让不同路径带上不同节拍",
        "sdg": "撤回一部分路径间的相位差",
        "t": "给路径加入一处较小的相位差",
        "tdg": "反向调整路径间的相位差",
        "ry": "重新分配两种测量结果的可能性",
        "rz": "改变路径之间的相对相位",
        "cx": "让一个比特的选择具体带动另一个比特",
        "cu1": "只给满足条件的路径加入相位差",
        "swap": "交换两个比特承载的信息",
        "ccx": "只有两个条件同时满足时才翻转目标比特",
    }.get(name, "按当前门的规则改变量子状态")


def trace_intuitive_example(
    operation: Gate,
    operation_index: int,
    operations: list[Gate | Measurement],
    experiment_kind: str,
) -> str:
    if isinstance(operation, Measurement):
        return f"测量 q{operation.qubit_idx} 后，本次运行只会把一个 0 或 1 写入 c{operation.cbit_idx}；重复很多次才形成柱状图。"
    name = operation.name.lower()
    qubits = operation.qubit_indices
    if name == "h" and is_recombining_h(operation, operation_index, operations, experiment_kind):
        return "前面的门已经让不同路径带上不同相位。这颗 H 把路径重新混合：有些振幅加强，有些振幅抵消，后面的测量概率因此可能变化。"
    if name == "h":
        return f"q{qubits[0]} 原本只有一条确定路径；这颗 H 把它展开成两条可以继续演化、以后也可以重新相遇的路径。"
    if name in {"s", "sdg", "t", "tdg", "rz", "cu1"}:
        return "可以把它想成给部分路径换了节拍：眼下 0/1 的出现概率可能看不出变化，但路径以后重新混合时会出现加强或抵消。"
    if name == "cx":
        return f"在当前电路里，q{qubits[0]}=0 时 q{qubits[1]} 不动；q{qubits[0]}=1 时 q{qubits[1]} 翻转。"
    if name == "x":
        return f"q{qubits[0]} 原来是 0 就变成 1，原来是 1 就变成 0。"
    if name == "swap":
        return f"q{qubits[0]} 和 q{qubits[1]} 像交换座位一样互换各自承载的信息。"
    if name == "ccx":
        return f"只有 q{qubits[0]} 和 q{qubits[1]} 都为 1 时，q{qubits[2]} 才会翻转。"
    if name == "ry":
        return f"这一步按角度 {operation.parameter} 调整 q{qubits[0]}，让以后测到 0 或 1 的比例发生变化。"
    return "当前门只按自己的确定规则处理经过这里的路径。"


def trace_simple_change(
    operation: Gate,
    operation_index: int,
    operations: list[Gate | Measurement],
    experiment_kind: str,
) -> str:
    if isinstance(operation, Measurement):
        return f"q{operation.qubit_idx} 的量子状态 → 本次经典结果 c{operation.cbit_idx}=0 或 1"
    name = operation.name.lower()
    qubits = operation.qubit_indices
    if name == "h":
        return (
            f"q{qubits[0]} 上带不同相位的路径 → 重新混合并产生加强/抵消"
            if is_recombining_h(operation, operation_index, operations, experiment_kind)
            else f"q{qubits[0]} 的一条确定路径 → 两条可继续演化的路径"
        )
    if name in {"s", "sdg", "t", "tdg", "rz", "cu1"}:
        return "路径的直接 0/1 概率可能暂时不变；路径之间的相对相位已经改变"
    if name == "cx":
        return f"q{qubits[0]}=0：q{qubits[1]} 不变；q{qubits[0]}=1：q{qubits[1]} 翻转"
    if name == "x":
        return f"q{qubits[0]}：0 ↔ 1"
    if name == "swap":
        return f"q{qubits[0]} 与 q{qubits[1]} 交换信息"
    if name == "ccx":
        return f"q{qubits[0]}=q{qubits[1]}=1 时，q{qubits[2]} 翻转"
    if name == "ry":
        return f"q{qubits[0]} 的振幅按角度 {operation.parameter} 重新分配"
    return "当前状态 → 按门规则得到下一状态"


def trace_explanation(
    operation: Gate,
    operation_index: int,
    operations: list[Gate | Measurement],
    experiment_kind: str,
    before: list[complex],
    after: list[complex],
    num_qubits: int,
) -> str:
    name = operation.name.lower()
    qubits = operation.qubit_indices
    phase_gates = {"s", "sdg", "t", "tdg", "rz", "cu1"}

    if name == "h" and experiment_kind in {"qft", "phase_interference"}:
        if is_recombining_h(operation, operation_index, operations, experiment_kind):
            return "前面的门已经让不同路径带上不同相位。这颗 H 会把这些路径重新混合：概率幅先发生相加或抵消，之后的测量才把新的振幅变成概率分布。"
        return f"这颗 H 先在 q{qubits[0]} 上制造多条可以发生干涉的路径，让后面的相位门有不同路径可以分别影响。"
    if name == "h":
        return f"这颗 H 让 q{qubits[0]} 不再只沿着一条确定路径前进，为后续关联或干涉准备多种可能。"
    if name in phase_gates:
        probability_note = "这一步各 basis state 的直接测量概率没有改变，" if probabilities_unchanged(before, after) else "这一步主要改变路径之间的相位关系，"
        return probability_note + "但相对相位已经变化；后续 H 等干涉门会把这份差异转成可见的概率变化。"
    if name == "cx":
        return f"这颗 CX 查看 q{qubits[0]}：它为 0 时 q{qubits[1]} 不动，为 1 时 q{qubits[1]} 翻转，因此两者的变化开始关联。"
    if name == "x":
        return f"X 把每条路径中的 q{qubits[0]} 从 0 翻为 1，或从 1 翻为 0。"
    if name == "swap":
        return f"SWAP 在每条路径中交换 q{qubits[0]} 与 q{qubits[1]} 承载的值。"
    if name == "ccx":
        return f"CCX 只在 q{qubits[0]}=1 且 q{qubits[1]}=1 的路径上翻转 q{qubits[2]}，其他路径保持不变。"
    if name == "ry":
        return f"RY({operation.parameter}) 旋转 q{qubits[0]}，因此重新分配各条路径的振幅和最终测量概率。"
    return "这一步按量子门的确定规则改变振幅；上方状态是直接计算得到的结果。"


def can_build_exact_trace(operations: list[Gate | Measurement], num_qubits: int) -> bool:
    if num_qubits > MAX_TRACE_QUBITS:
        return False
    state = [0j] * (2 ** num_qubits)
    state[0] = 1 + 0j
    try:
        for operation in operations:
            if isinstance(operation, Measurement):
                break
            state = apply_gate_to_state(state, operation, num_qubits)
            active_terms = sum(abs(amplitude) > TRACE_EPSILON for amplitude in state)
            if active_terms > MAX_TRACE_BASIS_STATES:
                return False
    except (TypeError, ValueError, ArithmeticError):
        return False
    return True


def beginner_state_formula_allowed(operation: Gate | Measurement, before: str | None, after: str | None) -> bool:
    if isinstance(operation, Measurement):
        return False
    if operation.name.lower() not in {"h", "x", "cx", "swap", "ccx"}:
        return False
    combined = f"{before or ''} {after or ''}"
    return "i" not in combined and "e^(" not in combined


def trace_math_note(
    operation: Gate | Measurement,
    before: str | None,
    after: str | None,
    state_before: list[complex] | None = None,
    num_qubits: int = 0,
) -> str:
    if isinstance(operation, Measurement):
        return "测量按各 basis state 的振幅模平方产生经典结果；这里不把测量后的分支继续写成单一纯态。"
    name = operation.name.lower()
    if name == "cx" and state_before is not None:
        return f"把 CX 的 basis-state 规则逐项作用于当前 statevector：{cx_basis_mapping(state_before, operation, num_qubits)}。"
    return f"将 {technical_label(operation)} 的线性变换作用于测量前的 statevector，得到下一行。该结果由服务端确定性计算，不由 LLM 生成。"


def probability_percent(probability: float) -> str:
    percentage = probability * 100
    if abs(percentage - round(percentage)) < 1e-8:
        return f"{int(round(percentage))}%"
    return f"{percentage:.1f}%"


def basis_bit(basis: int, qubit: int, num_qubits: int) -> int:
    return 1 if basis & qubit_mask(qubit, num_qubits) else 0


def qubit_measurement_probabilities(
    state: list[complex],
    qubit: int,
    num_qubits: int,
) -> dict[str, float]:
    probability_one = sum(
        abs(amplitude) ** 2
        for basis, amplitude in enumerate(state)
        if basis_bit(basis, qubit, num_qubits) == 1
    )
    probability_one = min(1.0, max(0.0, probability_one))
    return {"0": 1.0 - probability_one, "1": probability_one}


def predict_classical_counts(
    state: list[complex],
    measurements: list[Measurement],
    num_qubits: int,
    num_clbits: int,
) -> list[dict[str, Any]]:
    distribution: dict[str, float] = {}
    for basis, amplitude in enumerate(state):
        probability = abs(amplitude) ** 2
        if probability <= TRACE_EPSILON:
            continue
        classical_bits = ["0"] * num_clbits
        for measurement in measurements:
            classical_bits[measurement.cbit_idx] = str(basis_bit(basis, measurement.qubit_idx, num_qubits))
        result = "".join(reversed(classical_bits))
        distribution[result] = distribution.get(result, 0.0) + probability
    return [
        {"result": result, "probability": probability, "percent": probability_percent(probability)}
        for result, probability in sorted(distribution.items())
        if probability > TRACE_EPSILON
    ]


def measurement_analysis(
    state: list[complex],
    operation: Measurement,
    terminal_measurements: list[Measurement],
    num_qubits: int,
    num_clbits: int,
) -> dict[str, Any]:
    active_basis = [
        format(basis, f"0{num_qubits}b")
        for basis, amplitude in enumerate(state)
        if abs(amplitude) > TRACE_EPSILON
    ]
    qubit_rows = []
    for qubit in range(num_qubits):
        probabilities = qubit_measurement_probabilities(state, qubit, num_qubits)
        probability_zero = probabilities["0"]
        probability_one = probabilities["1"]
        if probability_zero >= 1 - TRACE_EPSILON:
            text = f"q{qubit}：必然得到 0"
        elif probability_one >= 1 - TRACE_EPSILON:
            text = f"q{qubit}：必然得到 1"
        else:
            text = (
                f"q{qubit}：约 {probability_percent(probability_zero)} 得到 0，"
                f"约 {probability_percent(probability_one)} 得到 1"
            )
        qubit_rows.append({
            "qubit": qubit,
            "probability_0": probability_zero,
            "probability_1": probability_one,
            "text": text,
        })

    measured = qubit_rows[operation.qubit_idx]
    measured_values = {
        bits[operation.qubit_idx]
        for bits in active_basis
    }
    if measured_values == {"0"}:
        measured_summary = (
            f"当前 {len(active_basis)} 个非零 basis state 中，q{operation.qubit_idx} 都等于 0，"
            f"所以测量 q{operation.qubit_idx} 时 c{operation.cbit_idx} 必然为 0。"
        )
    elif measured_values == {"1"}:
        measured_summary = (
            f"当前 {len(active_basis)} 个非零 basis state 中，q{operation.qubit_idx} 都等于 1，"
            f"所以测量 q{operation.qubit_idx} 时 c{operation.cbit_idx} 必然为 1。"
        )
    else:
        measured_summary = (
            f"当前 q{operation.qubit_idx} 有两种测量可能：约 {probability_percent(measured['probability_0'])} 得到 0，"
            f"约 {probability_percent(measured['probability_1'])} 得到 1；结果写入 c{operation.cbit_idx}。"
        )

    counts = (
        predict_classical_counts(state, terminal_measurements, num_qubits, num_clbits)
        if terminal_measurements else []
    )
    result_order = "".join(f"c{index}" for index in reversed(range(num_clbits)))
    counts_summary = "、".join(f"{item['result']}（约 {item['percent']}）" for item in counts)
    other_qubits = "；".join(row["text"] for row in qubit_rows if row["qubit"] != operation.qubit_idx)
    summary_parts = [
        f"测量前有 {len(active_basis)} 个非零 basis state：" + "、".join(f"|{bits}⟩" for bits in active_basis) + "。",
        measured_summary,
    ]
    if other_qubits:
        summary_parts.append("同时，" + other_qubits + "。")
    if counts_summary:
        summary_parts.append(f"最终结果按 {result_order} 排列时，预计主要为 {counts_summary}。")

    return {
        "state_order": "|" + " ".join(f"q{index}" for index in range(num_qubits)) + "⟩",
        "result_order": result_order,
        "active_basis_states": active_basis,
        "qubits": qubit_rows,
        "measured_qubit": operation.qubit_idx,
        "classical_bit": operation.cbit_idx,
        "measured_summary": measured_summary,
        "predicted_counts": counts,
        "summary": " ".join(summary_parts),
    }


def build_state_trace(
    operations: list[Gate | Measurement],
    serialized_operations: list[dict[str, Any]],
    experiment_kind: str,
    num_qubits: int,
    num_clbits: int,
) -> list[dict[str, Any]]:
    exact = can_build_exact_trace(operations, num_qubits)
    initial_bits = "0" * num_qubits
    state = [0j] * (2 ** num_qubits)
    state[0] = 1 + 0j
    initial_formula = f"|{initial_bits}⟩" if exact else None
    first_measurement_index = next(
        (index for index, operation in enumerate(operations) if isinstance(operation, Measurement)),
        None,
    )
    terminal_measurements = (
        [operation for operation in operations[first_measurement_index:] if isinstance(operation, Measurement)]
        if first_measurement_index is not None
        and all(isinstance(operation, Measurement) for operation in operations[first_measurement_index:])
        else []
    )
    trace = [{
        "index": 1,
        "trace_mode": "initial" if exact else "fallback",
        "purpose": "从所有量子比特都为 0 的已知状态开始",
        "concept": "初始状态",
        "technical": f"|{initial_bits}⟩",
        "before_state": None,
        "after_state": initial_formula,
        "change": f"当前状态：|{initial_bits}⟩" if exact else "完整状态轨迹已自动省略",
        "simple_change": "所有量子比特都从 0 开始",
        "explanation": (
            "先把实验放在一个完全已知、可以重复准备的起点。后面出现的每条路径都能追溯到这里。"
            if exact else (
                f"当前电路的完整状态超过 {MAX_TRACE_QUBITS} 个量子比特或 {MAX_TRACE_BASIS_STATES} 个非零 basis state 的可读上限；"
                "下面只展示局部规则和实验目的。"
            )
        ),
        "intuitive_example": f"当前有 {num_qubits} 个量子比特，它们现在都处于 0；还没有发生叠加、关联或测量。",
        "basis_help": describe_basis_states([initial_bits]),
        "show_simple_state": exact,
        "math_detail": {
            "before_state": None,
            "after_state": initial_formula,
            "gate_math": None,
            "note": "初始 statevector 只有 |0...0⟩ 的振幅为 1，其余 basis state 的振幅都为 0。",
        } if exact else None,
    }]
    measurement_started = False

    for position, (operation, serialized) in enumerate(zip(operations, serialized_operations), start=2):
        if isinstance(operation, Measurement):
            before_formula = None
            basis_help: list[str] = []
            analysis = None
            if exact:
                joint_state_formula, basis_bits = format_statevector(state, num_qubits)
                basis_help = describe_basis_states(basis_bits)
                before_formula = joint_state_formula
                analysis = measurement_analysis(
                    state,
                    operation,
                    terminal_measurements,
                    num_qubits,
                    num_clbits,
                )
                serialized["measurement_analysis"] = analysis
                serialized["intuitive_example"] = analysis["summary"]
                serialized["gate_card"]["current"] = {
                    "mode": "measurement_probability",
                    "before": joint_state_formula,
                    "after": analysis["measured_summary"],
                    "explanation": analysis["summary"],
                    "probabilities": analysis["qubits"][operation.qubit_idx],
                    "predicted_counts": analysis["predicted_counts"],
                    "state_order": analysis["state_order"],
                    "result_order": analysis["result_order"],
                }
            current_summary = analysis["summary"] if analysis else trace_intuitive_example(operation, position - 2, operations, experiment_kind)
            simple_change = analysis["measured_summary"] if analysis else trace_simple_change(operation, position - 2, operations, experiment_kind)
            trace.append({
                "index": position,
                "trace_mode": "measurement",
                "purpose": f"读取 q{operation.qubit_idx}，并把结果写入 c{operation.cbit_idx}",
                "concept": "测量",
                "technical": technical_label(operation),
                "before_state": before_formula,
                "after_state": None,
                "change": "量子态 → 一次经典测量结果；重复 shots → counts 概率分布",
                "simple_change": simple_change,
                "explanation": "测量会把量子状态读成经典的 0 或 1。",
                "intuitive_example": current_summary,
                "basis_help": basis_help,
                "show_simple_state": False,
                "measurement_analysis": analysis,
                "math_detail": {
                    "before_state": before_formula,
                    "after_state": None,
                    "gate_math": serialized["gate_card"]["math"],
                    "note": trace_math_note(operation, before_formula, None),
                },
                "operation_index": serialized["index"],
            })
            measurement_started = True
            continue

        if exact and not measurement_started:
            before = state
            try:
                after = apply_gate_to_state(before, operation, num_qubits)
                before_formula, before_bits = format_statevector(before, num_qubits)
                after_formula, after_bits = format_statevector(after, num_qubits)
                state = after
                explanation = trace_explanation(
                    operation,
                    position - 2,
                    operations,
                    experiment_kind,
                    before,
                    after,
                    num_qubits,
                )
                trace.append({
                    "index": position,
                    "trace_mode": "exact",
                    "purpose": trace_title(operation, position - 2, operations, experiment_kind),
                    "concept": serialized["title"],
                    "technical": serialized["technical"],
                    "before_state": before_formula,
                    "after_state": after_formula,
                    "change": f"{before_formula} → {after_formula}",
                    "simple_change": trace_simple_change(operation, position - 2, operations, experiment_kind),
                    "explanation": explanation,
                    "intuitive_example": trace_intuitive_example(operation, position - 2, operations, experiment_kind),
                    "basis_help": describe_basis_states(before_bits + after_bits),
                    "show_simple_state": beginner_state_formula_allowed(operation, before_formula, after_formula),
                    "math_detail": {
                        "before_state": before_formula,
                        "after_state": after_formula,
                        "gate_math": serialized["gate_card"]["math"],
                        "note": trace_math_note(operation, before_formula, after_formula, before, num_qubits),
                    },
                    "operation_index": serialized["index"],
                })
                continue
            except (TypeError, ValueError, ArithmeticError):
                exact = False

        trace.append({
            "index": position,
            "trace_mode": "fallback",
            "purpose": serialized["gate_card"]["why"],
            "concept": serialized["title"],
            "technical": serialized["technical"],
            "before_state": None,
            "after_state": None,
            "change": f"局部规则：{serialized['gate_card']['rule']}",
            "simple_change": trace_simple_change(operation, position - 2, operations, experiment_kind),
            "explanation": serialized["gate_card"]["why"],
            "intuitive_example": trace_intuitive_example(operation, position - 2, operations, experiment_kind),
            "basis_help": [],
            "show_simple_state": False,
            "math_detail": None,
            "operation_index": serialized["index"],
        })

    return trace


def build_current_change(
    operation: Gate | Measurement,
    operation_index: int,
    operations: list[Gate | Measurement],
    experiment_kind: str,
    num_qubits: int,
) -> dict[str, Any]:
    basis = infer_basis_before(operation_index, operations, num_qubits)
    standard_bell = experiment_kind == "bell" and is_standard_bell_prefix(operations)

    if isinstance(operation, Measurement):
        if standard_bell:
            prior_measurements = [item for item in operations[:operation_index] if isinstance(item, Measurement)]
            if prior_measurements:
                return {
                    "mode": "exact",
                    "before": "|00⟩ 或 |11⟩（由前一次测量分支决定）",
                    "after": f"c{operation.cbit_idx} 与前一测量结果保持关联",
                    "explanation": f"前一次测量已经选定 00 或 11 分支；测量 q{operation.qubit_idx} 并写入 c{operation.cbit_idx} 时，会记录同一分支对应的值。",
                }
            return {
                "mode": "exact",
                "before": "(|00⟩ + |11⟩) / √2",
                "after": f"c{operation.cbit_idx} = 0 或 1",
                "explanation": f"测量 q{operation.qubit_idx} 并写入 c{operation.cbit_idx}；多次运行后，Bell 电路会把相关的 00 / 11 组合统计出来。",
            }
        if basis is not None:
            value = basis[operation.qubit_idx]
            return {
                "mode": "exact",
                "before": format_ket(basis),
                "after": f"c{operation.cbit_idx} = {value}",
                "explanation": f"当前前缀仍是可确认的基态，因此测量 q{operation.qubit_idx} 会把 {value} 写入 c{operation.cbit_idx}。",
            }
        return {
            "mode": "local_rule",
            "before": None,
            "after": None,
            "explanation": f"q{operation.qubit_idx} 的完整状态受前面所有门共同影响，无法仅凭局部信息可靠写出；可以确认的是，测量结果会写入 c{operation.cbit_idx}，每次只能得到 0 或 1。",
        }

    name = operation.name.lower()
    qubits = operation.qubit_indices
    if standard_bell and name == "cx" and operation is next(item for item in operations if isinstance(item, Gate) and item.name.lower() == "cx"):
        return {
            "mode": "exact",
            "before": "(|00⟩ + |10⟩) / √2",
            "after": "(|00⟩ + |11⟩) / √2",
            "explanation": "q0=0 时 q1 保持 0；q0=1 时 q1 从 0 翻成 1。因此两个比特形成 00 / 11 的关联。",
        }

    if basis is not None:
        before = format_ket(basis)
        after_bits = list(basis)
        explanation = "当前电路前缀仍是一个可确认的基态，因此可以安全展示这一步的完整前后变化。"
        if name == "x":
            after_bits[qubits[0]] = "1" if after_bits[qubits[0]] == "0" else "0"
            after = format_ket(after_bits)
        elif name == "cx":
            if after_bits[qubits[0]] == "1":
                after_bits[qubits[1]] = "1" if after_bits[qubits[1]] == "0" else "0"
            after = format_ket(after_bits)
        elif name == "swap":
            after_bits[qubits[0]], after_bits[qubits[1]] = after_bits[qubits[1]], after_bits[qubits[0]]
            after = format_ket(after_bits)
            explanation = f"交换 q{qubits[0]} 与 q{qubits[1]} 后，两个位置承载的值互换。"
        elif name == "ccx":
            triggered = after_bits[qubits[0]] == after_bits[qubits[1]] == "1"
            if triggered:
                after_bits[qubits[2]] = "1" if after_bits[qubits[2]] == "0" else "0"
            after = format_ket(after_bits)
            explanation = "两个控制位都是 1，所以目标位发生翻转。" if triggered else "两个控制位没有同时为 1，所以目标位保持不变。"
        elif name == "h":
            zero_bits, one_bits = list(basis), list(basis)
            zero_bits[qubits[0]], one_bits[qubits[0]] = "0", "1"
            sign = "+" if basis[qubits[0]] == "0" else "−"
            after = f"({format_ket(zero_bits)} {sign} {format_ket(one_bits)}) / √2"
            explanation = f"H 把 q{qubits[0]} 的确定基态变成带相位关系的叠加，供后续门继续处理。"
        elif name == "ry":
            zero_bits, one_bits = list(basis), list(basis)
            zero_bits[qubits[0]], one_bits[qubits[0]] = "0", "1"
            if basis[qubits[0]] == "0":
                after = f"cos(θ/2){format_ket(zero_bits)} + sin(θ/2){format_ket(one_bits)}，θ={operation.parameter}"
            else:
                after = f"−sin(θ/2){format_ket(zero_bits)} + cos(θ/2){format_ket(one_bits)}，θ={operation.parameter}"
        elif name in {"s", "sdg", "t", "tdg", "rz", "cu1"}:
            after = f"{before}（基态标签不变，相位按门规则更新）"
            explanation = "当前是单一基态，门只更新相位；只有之后与其他路径干涉时，这个相位变化才可能显现在概率中。"
        else:
            after = before
        return {"mode": "exact", "before": before, "after": after, "explanation": explanation}

    return {
        "mode": "local_rule",
        "before": None,
        "after": None,
        "explanation": f"前面的门已经产生叠加或相位关系，当前完整状态无法在不做额外可靠模拟的情况下精确写出。这里仅确认作用对象：{technical_label(operation)}，并展示该门的局部规则。",
    }


def get_backend_runtime_readiness() -> dict[str, bool]:
    readiness = {}
    for backend_id, module_names in BACKEND_RUNTIME_IMPORTS.items():
        try:
            readiness[backend_id] = all(
                importlib.util.find_spec(module_name) is not None
                for module_name in module_names
            )
        except Exception:
            readiness[backend_id] = False
    return readiness


def get_local_backend_catalog() -> list[dict[str, Any]]:
    capability_data = load_backend_capabilities()
    runtime_readiness = get_backend_runtime_readiness()
    catalog = []
    for backend in capability_data["backends"]:
        backend_id = backend["id"]
        if backend_id not in LOCAL_BACKEND_TARGETS:
            continue
        catalog.append({
            **backend,
            "target": LOCAL_BACKEND_TARGETS[backend_id],
            "kind_label": BACKEND_LABELS["kind"].get(backend["kind"], backend["kind"]),
            "queue_label": BACKEND_LABELS["queue"].get(backend["queue"], backend["queue"]),
            "cost_label": BACKEND_LABELS["cost"].get(backend["cost"], backend["cost"]),
            "runtime_available": runtime_readiness.get(backend_id, False),
            "runtime_message": (
                "当前 Python 环境已具备运行依赖。"
                if runtime_readiness.get(backend_id, False)
                else BACKEND_RUNTIME_MESSAGES[backend_id]
            ),
        })
    return catalog


def parse_backend_recommendation(prompt: str, reply: str) -> dict[str, Any] | None:
    """Convert the public L2 backend reply into a product-layer response."""
    if not isinstance(reply, str):
        raise TypeError("L2 reply must be a string.")

    stripped = reply.strip()
    if stripped.upper().startswith("OPENQASM"):
        return None

    backend_id = None
    reason = ""
    no_match = False
    for line in stripped.splitlines():
        key, separator, value = line.partition(":")
        normalized_key = key.strip().lower()
        if separator and normalized_key == "recommended backend":
            backend_id = value.strip()
        elif separator and normalized_key == "reason":
            reason = value.strip()
        elif line.strip().lower().startswith("no backend satisfies"):
            no_match = True

    if backend_id is None and not no_match:
        raise ValueError("L2 reply is neither OpenQASM nor a backend recommendation.")

    catalog = get_local_backend_catalog()
    selected = next((backend for backend in catalog if backend["id"] == backend_id), None)
    if backend_id is not None and selected is None:
        raise ValueError(f"L2 recommended an unavailable Playground backend: {backend_id}")

    return {
        "response_type": "backend_recommendation",
        "message": "已完成后端推荐，本次未生成新电路。",
        "backends": catalog,
        "backend_recommendation": {
            "backend_id": backend_id,
            "reason": reason or (
                f"{selected['name']} 满足当前后端约束。" if selected else "当前本地后端均不能满足全部约束。"
            ),
            "requirements": extract_backend_requirements(prompt),
            "constraints_satisfied": selected is not None,
        },
    }


def recommend_backend(prompt: str, num_qubits: int) -> dict[str, Any]:
    user_requirements = extract_backend_requirements(prompt)
    requirements = dict(user_requirements)
    requirements["min_qubits"] = max(num_qubits, int(requirements.get("min_qubits", 0)))

    local_catalog = get_local_backend_catalog()
    local_ids = {backend["id"] for backend in local_catalog}
    matches = [
        backend for backend in find_matching_backends(requirements)
        if backend["id"] in local_ids
    ]
    preference_keys = set(user_requirements) - {"min_qubits"}

    preferred_order = [
        "braket_local_simulator",
        "originq_local_simulator",
        "spinq_taurus_simulator",
    ]
    selected = next(
        (backend for backend_id in preferred_order for backend in matches if backend["id"] == backend_id),
        None,
    )
    constraints_satisfied = selected is not None

    if selected is None:
        capacity_matches = [backend for backend in local_catalog if backend["max_qubits"] >= num_qubits]
        selected = max(capacity_matches or local_catalog, key=lambda backend: backend["max_qubits"])
        reason = (
            "当前只开放三个本地模拟器，用户约束没有完全匹配项；"
            f"暂选 {selected['name']}，你仍可手动切换。"
        )
    elif preference_keys:
        reason = (
            f"已复用 L2 的约束提取与能力校验：{selected['name']} 满足当前明确约束，"
            f"并可运行这个 {num_qubits} 比特电路。"
        )
    elif selected["id"] == "braket_local_simulator":
        reason = (
            f"当前电路使用 {num_qubits} 个量子比特；该后端免费、无需账号、无需排队，"
            "也是官方能力表中的评测推荐默认模拟器。"
        )
    else:
        reason = (
            f"当前电路使用 {num_qubits} 个量子比特；{selected['name']} 的容量最适合当前本地运行。"
        )

    return {
        "backend_id": selected["id"],
        "reason": reason,
        "requirements": requirements,
        "constraints_satisfied": constraints_satisfied,
    }


def classify_experiment(prompt: str, operations: list[Gate | Measurement]) -> str:
    normalized = prompt.lower()
    gate_names = [operation.name.lower() for operation in operations if isinstance(operation, Gate)]
    if "qft" in normalized or "傅里叶" in normalized:
        return "qft"
    if "干涉" in normalized or "相位" in normalized or any(name in {"cu1", "rz", "s", "sdg", "t", "tdg"} for name in gate_names):
        return "phase_interference"
    if "ghz" in normalized or (gate_names.count("cx") >= 2 and len({qubit for operation in operations if isinstance(operation, Gate) for qubit in operation.qubit_indices}) >= 3):
        return "ghz"
    if "bell" in normalized or "纠缠" in normalized or "绑在一起" in normalized:
        return "bell"
    if "硬币" in normalized or "coin" in normalized or (gate_names == ["h"]):
        return "coin"
    return "generic"


def technical_label(operation: Gate | Measurement) -> str:
    if isinstance(operation, Measurement):
        return f"Measure q{operation.qubit_idx} → c{operation.cbit_idx}"
    name = operation.name.lower()
    parameter = f"({operation.parameter})" if operation.parameter else ""
    qubits = operation.qubit_indices
    if name in {"cx", "cu1"}:
        return f"{name.upper()}{parameter}, control=q{qubits[0]}, target=q{qubits[1]}"
    if name == "ccx":
        return f"CCX, controls=q{qubits[0]}/q{qubits[1]}, target=q{qubits[2]}"
    if name == "swap":
        return f"SWAP q{qubits[0]} ↔ q{qubits[1]}"
    return f"{name.upper()}{parameter}, qubit=q{qubits[0]}"


def build_gate_card(
    operation: Gate | Measurement,
    operation_index: int,
    operations: list[Gate | Measurement],
    experiment_kind: str,
    num_qubits: int,
) -> dict[str, Any]:
    previous_gate = next((item for item in reversed(operations[:operation_index]) if isinstance(item, Gate)), None)
    next_gate = next((item for item in operations[operation_index + 1:] if isinstance(item, Gate)), None)

    if isinstance(operation, Measurement):
        return {
            "rule": "测量会把量子状态读成经典的 0 或 1。",
            "current": build_current_change(operation, operation_index, operations, experiment_kind, num_qubits),
            "why": "前面的量子变化本身看不见，必须测量后才能汇总成柱状图和 Raw counts。",
            "without": f"没有这一步，q{operation.qubit_idx} 就不会产生可展示的经典结果。",
            "math": gate_math(operation),
            "concept": "测量：把量子状态转换成一次可记录的经典结果",
            "technical": technical_label(operation),
        }

    name = operation.name.lower()
    qubits = operation.qubit_indices
    why = "这一步按照当前电路顺序改变状态，为后续操作和测量准备条件。"
    without = "去掉后，后续门接收到的状态会不同，最终测量分布也可能改变。"

    if name == "h" and experiment_kind == "bell":
        why = f"先让 q{qubits[0]} 保留 0 和 1 的多种可能，后面的 CX 才能把这种可能性扩展成两个比特的关联。"
        without = "去掉它，CX 缺少两种可能可供关联，电路通常只会沿着初始的 0 路径继续。"
    elif name == "h" and experiment_kind in {"qft", "phase_interference"}:
        phase_before = previous_gate and previous_gate.name.lower() in {"cu1", "rz", "s", "sdg", "t", "tdg"}
        if phase_before:
            why = f"前面的相位差不能直接测到；这里的 H 把 q{qubits[0]} 上的相位差重新变成 0/1 概率差，让干涉显现出来。"
            without = "去掉它，相位信息可能仍藏在状态里，直接测量很难看到它怎样改变结果。"
        else:
            why = f"这里先把 q{qubits[0]} 展开成多条可能路径，后续相位门才能让这些路径积累不同相位并发生干涉。"
            without = "去掉它，电路缺少可互相加强或抵消的多条路径，干涉现象会变得不明显。"
    elif name == "h" and experiment_kind == "coin":
        why = f"量子硬币需要先让 q{qubits[0]} 同时保留两种可测结果，重复运行时才会形成 0/1 分布。"
        without = "去掉它，量子比特会保持初始的 0，反复测量大多只会得到 0。"
    elif name == "cx":
        why = f"它让控制位 q{qubits[0]} 的不同可能决定目标位 q{qubits[1]} 是否翻转，把前一步的变化扩展到两个比特。"
        without = f"去掉它，q{qubits[1]} 不会跟随 q{qubits[0]} 建立这种条件关联。"
    elif name == "cu1":
        why = f"当前实验需要让 q{qubits[0]} 与 q{qubits[1]} 的部分可能路径带上不同相位，后续干涉才能把差异显现为概率变化。"
        without = "去掉它，这两条路径之间少了一处相位差，后续干涉图样会改变。"
    elif name in {"s", "sdg", "t", "tdg", "rz"}:
        why = f"它给 q{qubits[0]} 的不同可能加入相位差，为后面的干涉准备可比较的路径。"
        without = "去掉它，路径之间的相位关系会改变，后续测量概率可能失去当前的偏向。"
    elif name == "x":
        why = f"当前电路需要先把 q{qubits[0]} 准备成 1，作为后续受控操作或交换的明确输入。"
        without = "去掉它，这个比特会从 0 开始，后面的条件门可能不会触发。"
    elif name == "swap":
        why = f"当前实验要观察信息位置的变化，因此在这里交换 q{qubits[0]} 和 q{qubits[1]}。"
        without = "去掉它，两个量子比特各自承载的信息会留在原位。"
    elif name == "ccx":
        why = f"这里要表达“两个条件同时满足才行动”：q{qubits[0]} 和 q{qubits[1]} 都为 1 时才翻转 q{qubits[2]}。"
        without = f"去掉它，目标位 q{qubits[2]} 不会根据两个控制位共同变化。"
    elif name in {"ry", "rz"}:
        why = f"当前实验用参数 {operation.parameter} 精确控制 q{qubits[0]} 的变化幅度。"
        without = "去掉它，状态不会获得这次特定角度的旋转，测量分布会不同。"

    if next_gate and name == "h" and experiment_kind == "generic":
        why = f"它先为 q{qubits[0]} 准备多种可能，让下一步 {next_gate.name.upper()} 有可以继续处理的状态。"

    return {
        "rule": GATE_RULES[name],
        "current": build_current_change(operation, operation_index, operations, experiment_kind, num_qubits),
        "why": why,
        "without": without,
        "math": gate_math(operation),
        "concept": GATE_NAMES[name],
        "technical": technical_label(operation),
    }


def describe_operation(operation: Gate | Measurement) -> tuple[str, str]:
    if isinstance(operation, Measurement):
        return (
            "测量",
            f"测量 q{operation.qubit_idx}，结果写入 c{operation.cbit_idx}。",
        )

    name = operation.name.lower()
    qubits = operation.qubit_indices
    parameter = operation.parameter

    if name == "h":
        description = f"H 作用于 q{qubits[0]}，创建 0 和 1 的叠加。"
    elif name == "x":
        description = f"X 作用于 q{qubits[0]}，翻转这个量子比特的 0 和 1。"
    elif name in {"s", "sdg", "t", "tdg"}:
        description = f"{name.upper()} 作用于 q{qubits[0]}，调整量子态的相位。"
    elif name in {"ry", "rz"}:
        description = f"{name.upper()}({parameter}) 作用于 q{qubits[0]}，按给定角度旋转量子态。"
    elif name == "cx":
        description = f"CX 以 q{qubits[0]} 为控制、q{qubits[1]} 为目标，建立条件关联。"
    elif name == "cu1":
        description = f"CU1({parameter}) 以 q{qubits[0]} 为控制、q{qubits[1]} 为目标，施加受控相位。"
    elif name == "swap":
        description = f"SWAP 交换 q{qubits[0]} 与 q{qubits[1]} 的量子状态。"
    elif name == "ccx":
        description = f"CCX 以 q{qubits[0]}、q{qubits[1]} 为控制，在条件满足时翻转 q{qubits[2]}。"
    else:  # The shared L1 parser rejects unsupported gates before this point.
        description = f"{name.upper()} 作用于 {', '.join(f'q{q}' for q in qubits)}。"

    return GATE_NAMES[name], description


def serialize_operation(
    operation: Gate | Measurement,
    index: int,
    operations: list[Gate | Measurement],
    experiment_kind: str,
    num_qubits: int,
) -> dict[str, Any]:
    title, description = describe_operation(operation)
    gate_card = build_gate_card(operation, index - 1, operations, experiment_kind, num_qubits)
    intuitive_example = trace_intuitive_example(operation, index - 1, operations, experiment_kind)

    if isinstance(operation, Measurement):
        return {
            "index": index,
            "type": "measure",
            "qubit": operation.qubit_idx,
            "cbit": operation.cbit_idx,
            "title": title,
            "description": description,
            "purpose": "把看不见的量子状态变成可统计的 0/1 结果",
            "technical": technical_label(operation),
            "intuitive_example": intuitive_example,
            "gate_card": gate_card,
        }

    return {
        "index": index,
        "type": "gate",
        "gate": operation.name.lower(),
        "qubits": list(operation.qubit_indices),
        "parameter": operation.parameter,
        "title": title,
        "description": description,
        "purpose": GATE_PURPOSES[operation.name.lower()],
        "technical": technical_label(operation),
        "intuitive_example": intuitive_example,
        "gate_card": gate_card,
    }


def derive_title(prompt: str, num_qubits: int) -> str:
    normalized = prompt.lower()
    if "qft" in normalized or "傅里叶" in normalized:
        return f"{num_qubits} 比特量子傅里叶变换"
    if "干涉" in normalized or "相位" in normalized:
        return "相位干涉实验"
    if "ghz" in normalized:
        return f"{num_qubits} 比特 GHZ 态"
    if "硬币" in normalized or "coin" in normalized:
        return "量子硬币"
    if "bell" in normalized or "纠缠" in normalized:
        return "双比特纠缠实验" if num_qubits == 2 else "量子纠缠实验"
    return f"{num_qubits} 比特量子实验"


def build_experiment(prompt: str, qasm: str) -> dict[str, Any]:
    circuit = parse_qasm2(qasm)

    if circuit.num_qubits <= 0:
        raise ValueError("The generated circuit has no quantum register.")
    if not circuit.operations:
        raise ValueError("The generated circuit has no operations.")
    if not any(isinstance(operation, Measurement) for operation in circuit.operations):
        raise ValueError("The generated circuit has no measurement.")

    experiment_kind = classify_experiment(prompt, circuit.operations)
    backend_catalog = get_local_backend_catalog()
    backend_recommendation = recommend_backend(prompt, circuit.num_qubits)
    operations = [
        serialize_operation(operation, index, circuit.operations, experiment_kind, circuit.num_qubits)
        for index, operation in enumerate(circuit.operations, start=1)
    ]
    steps = build_state_trace(
        circuit.operations,
        operations,
        experiment_kind,
        circuit.num_qubits,
        circuit.num_clbits,
    )

    key_operations = [
        operation["index"]
        for operation in operations
        if operation["type"] == "gate" and operation["gate"] in {"h", "cx", "cu1", "rz", "swap", "ccx"}
    ][:3]
    result_explanation = {
        "meaning": "这些柱子展示每种测量结果在重复运行中出现的频率；它们描述本次运行，不自动证明实验“正确”。",
        "why": "结果分布来自电路中各个门依次改变状态，最后由 Measure 把状态转换成可统计的经典比特。",
        "gate_refs": key_operations,
    }
    if experiment_kind == "coin":
        result_explanation.update({
            "meaning": "如果 0 和 1 都多次出现，说明这枚量子硬币在重复测量中呈现概率分布。",
            "why": "H 先让 q0 保留两种可测可能，Measure 再把每次结果记录下来。",
        })
    elif experiment_kind in {"bell", "ghz"}:
        result_explanation.update({
            "meaning": "重点不是某一根柱子是否最高，而是多个比特的结果是否集中在少数有规律的组合上。",
            "why": "H 先准备多种可能，后续 CX 把这些可能扩展成多个量子比特之间的条件关联。",
        })
    elif experiment_kind in {"qft", "phase_interference"}:
        result_explanation.update({
            "meaning": "不同结果柱子的高低，显示相位差经过干涉后怎样转化成可见的测量概率。",
            "why": "相位门先让不同路径积累差异，H 等门再让路径互相加强或抵消，最终形成当前分布。",
        })

    return {
        "title": derive_title(prompt, circuit.num_qubits),
        "prompt": prompt,
        "kind": experiment_kind,
        "qasm": qasm,
        "circuit": {
            "num_qubits": circuit.num_qubits,
            "num_clbits": circuit.num_clbits,
            "operations": operations,
        },
        "steps": steps,
        "result_explanation": result_explanation,
        "backends": backend_catalog,
        "backend_recommendation": backend_recommendation,
    }


def validate_llm_config(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise ValueError("配置必须是 JSON 对象。")

    values: dict[str, str] = {}
    for field, label in (("base_url", "Base URL"), ("api_key", "API Key"), ("model", "Model")):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label} 不能为空。")
        values[field] = value.strip()

    if len(values["base_url"]) > 2048 or len(values["api_key"]) > 4096 or len(values["model"]) > 256:
        raise ValueError("API 配置字段过长。")

    parsed = urlsplit(values["base_url"])
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("Base URL 必须是有效的 http(s) 地址，且不能包含账号或密码。")

    return values


def classify_llm_error(exc: Exception) -> tuple[str, str]:
    detail = str(exc).lower()
    if any(marker in detail for marker in ("401", "403", "unauthorized", "authentication", "invalid api key")):
        return "invalid_api_key", "API Key 无效或没有调用权限。"
    if any(marker in detail for marker in ("model_not_found", "model not found", "unknown model")) or ("404" in detail and "model" in detail):
        return "model_unavailable", "Model 不存在，或当前 API Key 没有使用权限。"
    if "404" in detail:
        return "base_url_unreachable", "Base URL 没有提供 OpenAI-compatible chat/completions 接口。"
    if any(marker in detail for marker in ("429", "rate limit", "too many requests")):
        return "rate_limited", "服务商请求过于频繁或额度不足，请稍后重试。"
    if any(marker in detail for marker in ("timed out", "timeout")):
        return "llm_timeout", "LLM 请求超时，请检查网络或稍后重试。"
    if any(marker in detail for marker in ("connection error", "name or service", "refused", "unreachable", "urlopen error")):
        return "base_url_unreachable", "Base URL 无法访问，请检查地址和网络。"
    if "invalid llm response format" in detail:
        return "invalid_llm_response", "服务商返回了不兼容的响应格式。"
    if any(marker in detail for marker in ("l2 agent failed", "loomq protocol", "validation error")):
        return "invalid_llm_result", "L2 返回的内容不是 LoomQ 可用的实验方案。"
    return "llm_call_failed", "LLM 调用失败，请检查 Base URL、API Key 和 Model。"


class ProductRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._session_id: str | None = None
        self._set_session_cookie = False
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def do_GET(self) -> None:  # noqa: N802
        request_path = urlsplit(self.path).path
        if request_path == "/api/runtime-readiness":
            catalog = get_local_backend_catalog()
            self._send_json(
                HTTPStatus.OK,
                {
                    "ready": all(backend["runtime_available"] for backend in catalog),
                    "backends": [
                        {
                            "id": backend["id"],
                            "runtime_available": backend["runtime_available"],
                            "runtime_message": backend["runtime_message"],
                        }
                        for backend in catalog
                    ],
                },
            )
            return
        if request_path == "/api/llm-config":
            session_id = self._get_session_id()
            self._send_json(
                HTTPStatus.OK,
                SESSION_STORE.status(session_id, get_environment_llm_config()),
            )
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        request_path = urlsplit(self.path).path
        if request_path not in {
            "/api/generate",
            "/api/run",
            "/api/llm-config/test",
            "/api/llm-config",
        }:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_request", "message": "无效的请求长度。"})
            return

        if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_request", "message": "请求内容为空或过大。"})
            return

        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_json", "message": "请求必须是有效的 JSON。"})
            return

        if request_path == "/api/llm-config/test":
            self._handle_llm_config_test(payload)
            return

        if request_path == "/api/llm-config":
            self._handle_llm_config_apply(payload)
            return

        if request_path == "/api/run":
            self._handle_run(payload)
            return

        prompt = payload.get("prompt") if isinstance(payload, dict) else None
        if not isinstance(prompt, str) or not prompt.strip():
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_prompt", "message": "prompt 必须是非空字符串。"})
            return

        prompt = prompt.strip()
        session_id = self._get_session_id()
        config = SESSION_STORE.active_config(session_id)
        if config is None and get_environment_llm_config() is None:
            self._send_json(
                HTTPStatus.PRECONDITION_REQUIRED,
                {"error": "llm_not_configured", "message": "请先在右上角连接自己的 LLM API。"},
            )
            return

        token = (
            set_runtime_llm_config(config["base_url"], config["api_key"], config["model"])
            if config is not None
            else None
        )
        try:
            reply = adapter.agent_chat(prompt)
            backend_only = parse_backend_recommendation(prompt, reply)
            experiment = None if backend_only is not None else build_experiment(prompt, reply)
        except RuntimeError as exc:
            if config is not None:
                SESSION_STORE.set_connected(session_id, False)
            error, message = classify_llm_error(exc)
            self._send_json(HTTPStatus.BAD_GATEWAY, {"error": error, "message": message})
            return
        except (TypeError, ValueError):
            self._send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": "invalid_qasm", "message": "L2 返回的 QASM 未通过现有 L1 parser/IR 校验。"})
            return
        except Exception:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal_error", "message": "服务端处理生成请求时发生错误。"})
            return
        finally:
            if token is not None:
                reset_runtime_llm_config(token)

        if config is not None:
            SESSION_STORE.set_connected(session_id, True)
        self._send_json(
            HTTPStatus.OK,
            backend_only if backend_only is not None else {"response_type": "experiment", "experiment": experiment},
        )

    def _handle_llm_config_test(self, payload: Any) -> None:
        try:
            config = validate_llm_config(payload)
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_llm_config", "message": str(exc)})
            return

        session_id = self._get_session_id()
        SESSION_STORE.clear_pending(session_id)
        token = set_runtime_llm_config(config["base_url"], config["api_key"], config["model"])
        try:
            reply = call_llm(
                [
                    {"role": "system", "content": "You are a connection check. Reply with OK only."},
                    {"role": "user", "content": "OK"},
                ],
                timeout=LLM_TEST_TIMEOUT_SECONDS,
            )
            if not isinstance(reply, str) or not reply.strip():
                raise RuntimeError("Invalid LLM response format")
        except Exception as exc:
            error, message = classify_llm_error(exc)
            self._send_json(HTTPStatus.BAD_GATEWAY, {"error": error, "message": message, "connected": False})
            return
        finally:
            reset_runtime_llm_config(token)

        SESSION_STORE.set_pending(session_id, config)
        self._send_json(
            HTTPStatus.OK,
            {
                "connected": True,
                "base_url": config["base_url"],
                "model": config["model"],
                "message": "连接测试成功，可以应用此配置。",
            },
        )

    def _handle_llm_config_apply(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_request", "message": "请求必须是 JSON 对象。"})
            return

        session_id = self._get_session_id()
        config = SESSION_STORE.apply_pending(session_id)
        if config is None:
            self._send_json(
                HTTPStatus.CONFLICT,
                {"error": "llm_config_not_tested", "message": "请先测试连接，再应用配置。"},
            )
            return

        self._send_json(
            HTTPStatus.OK,
            {
                "configured": True,
                "connected": True,
                "base_url": config["base_url"],
                "model": config["model"],
                "has_api_key": True,
            },
        )

    def _handle_run(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_request", "message": "请求必须是 JSON 对象。"})
            return

        qasm = payload.get("qasm")
        shots = payload.get("shots")
        backend_id = payload.get("backend_id")

        if not isinstance(qasm, str) or not qasm.strip():
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_qasm", "message": "qasm 必须是非空字符串。"})
            return
        if not isinstance(shots, int) or isinstance(shots, bool) or not 100 <= shots <= 8192:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid_shots", "message": "shots 必须是 100 到 8192 之间的整数。"})
            return
        if not isinstance(backend_id, str) or backend_id not in LOCAL_BACKEND_TARGETS:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "unsupported_backend", "message": "backend_id 必须是当前开放的本地模拟器。"})
            return

        backend = next(
            item for item in get_local_backend_catalog()
            if item["id"] == backend_id
        )
        target = LOCAL_BACKEND_TARGETS[backend_id]
        started_at = time.perf_counter()

        if not backend["runtime_available"]:
            self._send_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {
                    "error": "backend_dependency_missing",
                    "message": backend["runtime_message"],
                },
            )
            return

        try:
            result = adapter.run(qasm.strip(), target, shots)
        except (ImportError, ModuleNotFoundError):
            self._send_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {
                    "error": "backend_dependency_missing",
                    "message": BACKEND_RUNTIME_MESSAGES[backend_id],
                },
            )
            return
        except (KeyError, TypeError, ValueError) as exc:
            self._send_json(HTTPStatus.UNPROCESSABLE_ENTITY, {"error": "invalid_circuit", "message": f"电路无法运行：{exc}"})
            return
        except RuntimeError:
            self._send_json(HTTPStatus.BAD_GATEWAY, {"error": "execution_failed", "message": f"{backend['name']} 执行失败，请稍后重试。"})
            return
        except Exception:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "internal_error", "message": "服务端运行电路时发生错误。"})
            return

        response_result = dict(result)
        response_result["elapsed_seconds"] = round(time.perf_counter() - started_at, 3)
        response_result["backend_id"] = backend_id
        response_result["backend_name"] = backend["name"]
        response_result["target"] = target
        self._send_json(HTTPStatus.OK, {"result": response_result})

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if self._set_session_cookie and self._session_id:
            secure_attribute = "; Secure" if self.headers.get("X-Forwarded-Proto", "").lower() == "https" else ""
            self.send_header(
                "Set-Cookie",
                f"{SESSION_COOKIE_NAME}={self._session_id}; Path=/; HttpOnly; SameSite=Lax{secure_attribute}",
            )
        self.end_headers()
        self.wfile.write(body)

    def _get_session_id(self) -> str:
        if self._session_id:
            return self._session_id

        candidate = None
        raw_cookie = self.headers.get("Cookie", "")
        if raw_cookie:
            cookie = SimpleCookie()
            try:
                cookie.load(raw_cookie)
                morsel = cookie.get(SESSION_COOKIE_NAME)
                candidate = morsel.value if morsel else None
            except Exception:
                candidate = None

        self._session_id, self._set_session_cookie = SESSION_STORE.ensure(candidate)
        return self._session_id


class ProductServer(ThreadingHTTPServer):
    daemon_threads = True


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the LoomQ product service.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=4173, type=int)
    args = parser.parse_args()

    server = ProductServer((args.host, args.port), ProductRequestHandler)
    print(f"LoomQ product service: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
