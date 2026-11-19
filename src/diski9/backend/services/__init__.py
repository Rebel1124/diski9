"""Competition services (Phase 6C.3): business rules over the repositories.

Every service takes a server-built :class:`~diski9.backend.auth.permissions.Principal`
(never a client-supplied user ID), checks its capability, and runs its writes in
one explicit transaction with the database clock. Errors are typed
(:mod:`.common`) and carry user-safe messages.
"""
