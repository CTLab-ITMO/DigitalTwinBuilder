"""
Top-level package for digital_twin_builder.

Важно: здесь намеренно НЕ импортируются тяжёлые подмодули (sensors, ipcamera,
DTlibrary и т.п.), чтобы избежать побочных эффектов и падений из-за
отсутствующих нативных расширений при простом `import digital_twin_builder`.

Используйте явные импорты, например:

    from digital_twin_builder.DTlibrary.agents.orchestrator_agent import OrchestratorAgent
"""

__all__: list[str] = []
