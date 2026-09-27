"""The in-app assistant: questions about runs, config, governance and outputs.

It is read-only and grounded. Every factual claim it makes has to come from a
tool observation over a real run, and the tools are the only way it sees data
-- there is no path by which it can quote a number it was not handed.

The model itself is whatever OpenAI-compatible endpoint the deployment
configures. Nothing here requires a particular provider, and with nothing
configured the feature reports itself unavailable rather than half-working.
"""
from .agent import answer, seed_context  # noqa: F401
from .config import AssistantConfig, load_config  # noqa: F401
from .tools import TOOL_CATALOGUE, execute_tool  # noqa: F401
