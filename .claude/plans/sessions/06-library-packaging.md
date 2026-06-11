# Session 6: Library Packaging + Plugins

## Objective
Make ourgraph a proper installable library with a plugin system that allows users to extend functionality (LLM providers, data sources, context sources) without modifying core code.

## Context
The user wants "ourgraph should be built as an external library as well, which supports building the knowledge graph and letting the users plug it into any LLMs of their choice and ask questions or rebuild relationships according to their needs."

## Tasks

### 1. Review and Update Project Structure
**Current structure**:
```
src/ourgraph/
├── __init__.py
├── cli.py
├── config.py
├── constants.py
├── db/
├── graph/
├── graphiti_layer/
├── ingest/
├── llm/
├── nlp/ (to be created in Session 4)
├── context/ (to be created in Session 5)
└── utils/
```

**Ensure proper packaging** in `pyproject.toml`:
```toml
[project]
name = "ourgraph"
version = "0.1.0"
description = "Vietnamese stock market knowledge graph library"
# ... (already exists)

[project.entry-points."ourgraph.plugins"]
# Plugin entry points will be registered here

[tool.hatch.build.targets.wheel]
packages = ["src/ourgraph"]
```

### 2. Create Plugin System
**File**: `src/ourgraph/plugins/__init__.py` (new)

```python
"""Plugin system for ourgraph.

Plugins can extend:
- LLM providers (ourgraph.plugins.llm)
- Data sources (ourgraph.plugins.source)
- Context sources (ourgraph.plugins.context)
"""

class PluginRegistry:
    """Registry for ourgraph plugins."""
    
    _plugins: dict[str, dict[str, type]] = {
        "llm": {},
        "source": {},
        "context": {},
    }
    
    @classmethod
    def register(cls, category: str, name: str, plugin_class: type) -> None:
        """Register a plugin."""
        cls._plugins[category][name] = plugin_class
    
    @classmethod
    def get(cls, category: str, name: str) -> type | None:
        """Get a registered plugin."""
        return cls._plugins[category].get(name)
    
    @classmethod
    def list(cls, category: str | None = None) -> dict:
        """List registered plugins."""
        if category:
            return cls._plugins.get(category, {})
        return cls._plugins
```

### 3. LLM Plugin Interface
**File**: `src/ourgraph/plugins/llm.py` (new)

```python
from ourgraph.llm.provider import LLMProvider

class LLMPlugin(LLMProvider):
    """Base class for LLM plugins.
    
    To create a plugin:
    1. Subclass LLMPlugin
    2. Implement: chat(), embed(), rerank()
    3. Register: PluginRegistry.register("llm", "my_provider", MyPlugin)
    
    Or use entry points in setup.cfg/pyproject.toml:
    [ourgraph.plugins.llm]
    my_provider = my_package.my_module:MyPlugin
    """
    pass
```

### 4. Data Source Plugin Interface
**File**: `src/ourgraph/plugins/source.py` (new)

```python
class DataSourcePlugin:
    """Base class for data source plugins.
    
    Examples: vnstock, World Bank, IMF, yfinance are built-in.
    Users can add: Fireant, StoxPlus, etc.
    """
    
    @abstractmethod
    async def fetch_symbols(self) -> list[str]:
        """Fetch available symbols."""
        pass
    
    @abstractmethod
    async def fetch_company_data(self, symbol: str) -> dict:
        """Fetch company overview, officers, shareholders, etc."""
        pass
    
    @abstractmethod
    async def fetch_prices(self, symbol: str, ...) -> list[dict]:
        """Fetch historical prices."""
        pass
```

### 5. Context Source Plugin Interface
**File**: `src/ourgraph/plugins/context.py` (new)

```python
class ContextSourcePlugin:
    """Base class for context source plugins.
    
    Future plugins:
    - NewsSourcePlugin (CafeF, VnExpress, ...)
    - RSSPlugin
    - APIPlugin (generic REST API)
    """
    
    @abstractmethod
    async def fetch_context(self, **kwargs) -> str | dict:
        """Fetch context from this source."""
        pass
```

### 6. Document Plugin Development
**File**: `docs/plugins.md` (new, or in README)

```markdown
## Creating Plugins

### LLM Provider Plugin

1. Create a class that implements `LLMProvider`:
\```python
from ourgraph.llm.provider import LLMProvider

class MyLLMPlugin(LLMProvider):
    def __init__(self, api_key: str, ...):
        ...
    
    async def chat(self, messages, **kwargs):
        ...
\```

2. Register it:
\```python
from ourgraph.plugins import PluginRegistry
PluginRegistry.register("llm", "my_provider", MyLLMPlugin)
\```

3. Use it:
\```bash
LLM_PROVIDER=my_provider MY_LLM_API_KEY=... ourgraph query "..."
\```
```

### 7. Create Usage Examples
**Directory**: `examples/` (new)

**File**: `examples/basic_usage.py`
```python
"""Basic usage example."""
from ourgraph import GraphBuilder, GraphQueries, Pipeline
from ourgraph.config import get_settings

settings = get_settings()

# Build graph
builder = GraphBuilder.from_settings(settings.falkordb)
await builder.upsert_companies(...)

# Query graph
queries = GraphQueries.from_settings(settings.falkordb)
peers = await queries.get_sector_peers("HPG")
```

**File**: `examples/custom_llm_provider.py`
```python
"""Example: Custom LLM provider plugin."""
from ourgraph.llm.provider import LLMProvider
from ourgraph.plugins import PluginRegistry

class FireworksPlugin(LLMProvider):
    """LLM provider using Fireworks AI."""
    ...

PluginRegistry.register("llm", "fireworks", FireworksPlugin)
```

**File**: `examples/natural_language_queries.py`
```python
"""Example: Query the knowledge graph with natural language."""
from ourgraph import GraphRAGSearch

search = await GraphRAGSearch.create(settings)
results = await search.query("What are HPG's main subsidiaries?")
```

### 8. Update README
**File**: `README.md` (modify)

Add sections:
- Installation: `pip install ourgraph`
- Library usage (Python API)
- Plugin development guide
- CLI reference
- Configuration reference

### 9. Tests
**File**: `tests/test_plugins.py` (new)

- Test plugin registration
- Test plugin discovery (entry points)
- Test custom LLM plugin
- Test custom data source plugin

## Acceptance Criteria
- [ ] Project is properly packaged: `pip install -e .` works
- [ ] Plugin system implemented with registry
- [ ] LLM plugin interface documented
- [ ] Data source plugin interface documented
- [ ] Context source plugin interface documented
- [ ] Example files created in `examples/`
- [ ] README updated with library usage docs
- [ ] All tests pass: `pytest tests/test_plugins.py -v`

## CLI Testing
```bash
# Install in development mode
pip install -e .

# Use as library
python examples/basic_usage.py

# List available plugins
ourgraph plugins list

# Use custom plugin
LLM_PROVIDER=my_plugin ourgraph query "..."
```

## Notes
- Entry points (setup.cfg/pyproject.toml) allow plugins to be auto-discovered
- Consider using `importlib.metadata.entry_points` for plugin discovery
- Plugins should be able to add CLI subcommands (advanced)
- Document that plugins can be installed separately: `pip install ourgraph-fireworks-plugin`
