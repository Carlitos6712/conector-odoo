"""``/admin/api/vault``: status of the credential-vault key and one-time key generation.

Generating needs the admin role and CSRF (the shared guard) and only works while NO key is
configured (env or file): otherwise 409. The key is written to a 0600 file and never returned.
"""

from fastapi import APIRouter

from conector_odoo.infrastructure.admin_api.deps import AdminDep
from conector_odoo.infrastructure.admin_api.schemas.vault import VaultStatusOut

router = APIRouter(prefix="/vault", tags=["admin-vault"])


@router.get("/status")
async def get_status(admin: AdminDep) -> VaultStatusOut:
    configured, source = admin.vault_key.status()
    return VaultStatusOut(configured=configured, source=source)


@router.post("/generate", status_code=201)
async def generate(admin: AdminDep) -> VaultStatusOut:
    admin.vault_key.generate()
    configured, source = admin.vault_key.status()
    return VaultStatusOut(configured=configured, source=source)
