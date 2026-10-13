"""Interpret product extension of the foundation repository manager.

Product services and routers depend on this subclass instead of the foundation
``RepositoryManager`` so the foundation stays free of product repositories.
Code that receives a foundation manager wraps its session via
``InterpretRepositoryManager(repos.db)`` to join the same transaction.
"""

from functools import cached_property

from src.foundation.repositories.repository_manager import RepositoryManager
from src.interpret.repositories.conversation import ConversationRepository


class InterpretRepositoryManager(RepositoryManager):
    @cached_property
    def conversation(self) -> ConversationRepository:
        return ConversationRepository(self.db)
