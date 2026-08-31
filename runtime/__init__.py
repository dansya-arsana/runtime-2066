"""2066 — AI-native semantic runtime. Milestone 4c: applications + export.

Pipeline: parse -> analyze (validate) -> execute (roadmap §10), with a
mechanical cast-repair loop (§13/§80), a canonical serializer + deterministic
hash (§15), two equivalent execution adapters (§102, Appendix F.3), a
capability-gated effect layer (Phase 3–4), signed agent identities (§26),
and an export backend to conventional source (§10/§4.10).
"""

from .errors import StructuredError
from .export import export_javascript, export_python
from .hashing import program_hash
from .identity import Identity, canonical_json, generate_identity
from .parser import Function, Node, Program, parse_source
from .plan_vm import Plan, compile_plan, execute_plan
from .repair import RepairOutcome, repair_source
from .serialize import serialize_program
from .capabilities import sign_capabilities, verify_envelope
from .validator import Analysis, analyze, program_effects
from .interpreter import execute

__version__ = "1.4.1"

__all__ = [
    "Analysis",
    "Function",
    "Identity",
    "Node",
    "Plan",
    "Program",
    "RepairOutcome",
    "StructuredError",
    "__version__",
    "analyze",
    "canonical_json",
    "compile_plan",
    "execute",
    "execute_plan",
    "export_python",
    "export_javascript",
    "generate_identity",
    "parse_source",
    "program_effects",
    "program_hash",
    "repair_source",
    "serialize_program",
    "sign_capabilities",
    "verify_envelope",
]
