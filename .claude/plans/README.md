# ourgraph Implementation Plans

This directory contains the session breakdowns for building the ourgraph Vietnamese stock market knowledge graph.

## Session Breakdown

Sessions are designed to be executed sequentially within each phase, but some can be worked on in parallel if dependencies allow.

### [Session 1: Relationship System Redesign](sessions/01-relationship-redesign.md) ✅
- Fix chaotic relationships in the graph
- Create comprehensive relationship taxonomy
- Build RelationshipManager with validation
- **Dependencies**: None (start here)
- **Status**: Complete (all 56 tests pass, lint clean)
- **Deliverables**: `relationship_schema.py`, `relationship_manager.py`, derived role edges (IS_BOARD_MEMBER, IS_FOUNDER, IS_EXECUTIVE), ORM traversal methods, subsidiary validation, `docs/graph-schema.md`

### [Session 2: Hidden Relationship Discovery](sessions/02-hidden-relationship-discovery.md) ✅
- Build algorithms to discover hidden relationships
- Cross-shareholdings, subsidiary chains, influence networks
- Supply chain inference, price correlation analysis
- **Dependencies**: Session 1 (relationship system)
- **Status**: Complete (all 79 tests pass, lint clean)
- **Deliverables**: `graph/discovery.py`, `graph/queries.py` (query_raw), `cli.py` (graph discover), discovery engine with 10+ methods, 23 discovery tests

### [Session 3: LLM Provider Abstraction](sessions/03-llm-abstraction.md)
- Build provider-agnostic LLM abstraction
- Support OpenAI, Anthropic, Ollama, and any OpenAI-compatible API
- **Dependencies**: None (can start anytime)
- **Estimated time**: 2-3 hours

### [Session 4: Natural Language Creation](sessions/04-natural-language-creation.md)
- Allow users to create relationships via natural language
- LLM-powered relationship extraction
- Entity resolution and confirmation flow
- **Dependencies**: Session 3 (LLM), Session 1 (relationships)
- **Estimated time**: 3-4 hours

### [Session 5: Context Update Mechanism](sessions/05-context-update-mechanism.md)
- Build self-adapting mechanism for graph updates
- Temporal relationship management
- Context file parsing (text, JSON, graph)
- Conflict resolution strategies
- **Dependencies**: Session 1 (relationships), Session 4 (NLP extraction)
- **Estimated time**: 4-5 hours

### [Session 6: Library Packaging + Plugins](sessions/06-library-packaging.md)
- Make ourgraph a proper installable library
- Build plugin system for LLMs, data sources, context sources
- Create usage examples and documentation
- **Dependencies**: Sessions 1-5 (core functionality)
- **Estimated time**: 3-4 hours

### [Session 7: Performance + Testing](sessions/07-performance-testing.md)
- Profile and optimize the ingestion pipeline
- Add batch operations and caching
- Comprehensive test coverage (>80%)
- Performance benchmarks
- **Dependencies**: All previous sessions
- **Estimated time**: 3-4 hours

### [Session 8: Advanced Queries + Visualization](sessions/08-advanced-queries.md)
- Multi-hop reasoning and comparative queries
- Temporal queries (what was true at time X?)
- Graph visualization and export
- Interactive query session
- **Dependencies**: Sessions 1, 2, 3
- **Estimated time**: 3-4 hours

## Execution Order

### Phase 1: Core Graph (Do First)
1. **Session 1**: Relationship System Redesign
2. **Session 2**: Hidden Relationship Discovery

### Phase 2: Intelligence Layer
3. **Session 3**: LLM Provider Abstraction
4. **Session 4**: Natural Language Creation
5. **Session 5**: Context Update Mechanism

### Phase 3: Packaging + Polish
6. **Session 6**: Library Packaging + Plugins
7. **Session 7**: Performance + Testing
8. **Session 8**: Advanced Queries + Visualization

## Parallel Opportunities

After Phase 1 is complete:
- Session 3 and Session 4 can be worked on in parallel (different developers)
- Session 6 can start once Sessions 1-5 are done
- Session 7 and Session 8 can be worked on in parallel

## Quick Reference

### Start a Session
```bash
# Read the session plan
cat plans/sessions/01-relationship-redesign.md

# Create a feature branch
git checkout -b feat/session-1-relationship-redesign

# Work through the tasks...
# Commit when done
git add -A
git commit -m "feat: implement relationship system redesign"
```

### Track Progress
```bash
# Mark a session as complete
echo "[x] Session 1 complete" >> plans/README.md
```

## Notes
- Each session file contains detailed tasks, acceptance criteria, and CLI testing commands
- All sessions include test requirements
- "Extremely free" is maintained: Ollama remains the default LLM
- The design is modular from the start - plugins for future news sources, etc.
- Sessions are designed to be completable in 1-2 coding sessions each
