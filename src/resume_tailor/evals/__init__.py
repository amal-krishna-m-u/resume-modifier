"""Prompt and model evals (OQ-10): "did prompt v2 select better than v1?"

Cases live in `evals/` at the project root, which is gitignored: a case is a real
job posting plus the facts a real resume drew on, i.e. the career record again.
"""

from .cases import Case, build_case, load_cases, save_case
from .runner import compare, load_result, run_eval

__all__ = ["Case", "build_case", "compare", "load_cases", "load_result", "run_eval", "save_case"]
