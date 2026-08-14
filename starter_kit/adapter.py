#!/usr/bin/env python3
"""LoomQ submission adapter contract v1.0.

This file intentionally contains no scoring implementation. Teams may implement
the functions directly or delegate to another language/runtime with subprocess.
"""

from typing import Any, Dict, List, Tuple
from l1 import transpile_l1,run_l1
from l2 import agent_chat_l2

SUPPORTED_TARGETS = ("spinq", "originq", "braket")

def transpile(qasm_str: str,target: str) -> str:
    """Translate OpenQASM 2.0 into the target backend's native representation."""
    return transpile_l1(qasm_str,target)

#def transpile(qasm_str: str, target: str) -> str:
#    """Translate OpenQASM 2.0 into the target backend's native representation."""
#    target = target.strip().lower()
#    if target not in SUPPORTED_TARGETS:
#        raise ValueError(
#            f"Unsupported target: {target}"
#        )
#
#    circuit = parse_qasm2(qasm_str)
#
#    if target == "spinq":
#        return emit_spinq(
#            circuit
#        )
#
#    elif target == "braket":
#        return emit_braket(
#            circuit
#        )
#
#    elif target == "originq":
#        return emit_originq(
#            circuit
#        )
#
#    raise ValueError(
#        f"Unsupported target: {target}"
#    )
def run(qasm_str: str, target: str, shots: int) -> Dict[str, Any]:
    """Execute a circuit and return the unified result schema from the rules."""

    return run_l1(qasm_str,target,shots)
    
#def run(qasm_str: str, target: str, shots: int) -> Dict[str, Any]:
#    """Execute a circuit and return the unified result schema from the rules."""
#    target = target.strip().lower()
#    if target not in SUPPORTED_TARGETS:
#            raise ValueError(
#                f"Unsupported target: {target}"
#            )
#    
#    circuit = parse_qasm2(qasm_str)
# 
#    if target == "spinq":
# 
#        return run_spinq(
#            circuit,
#            shots
#        )
# 
#    elif target == "braket":
# 
#        return run_braket(
#            circuit,
#            shots
#        )
# 
#    elif target == "originq":
# 
#        return run_originq(
#            circuit,
#            shots
#        )
# 
#    raise ValueError(
#        f"Unsupported target: {target}"
#    )
#    
def agent_chat(prompt: str) -> str:
    """Optional L2 entry point using the documented LOOMQ_LLM_* environment."""

    return agent_chat_l2(
        prompt
    )

def compile_hybrid(hybrid_qasm_str: str) -> Tuple[List[str], str]:
    """Optional L3 entry point. Return quantum operations and RISC-V assembly."""
    raise NotImplementedError(
        "L3 is optional; implement compile_hybrid(hybrid_qasm_str) to enter"
    )
