"""
ARIA-OS: Supabase Artifacts Service
Implements the ADK BaseArtifactService to store agent-generated files
(like PDFs, reports, or processed images) directly in Supabase Storage.
"""
import io
from pathlib import Path
from typing import Any

from src.infra.db import get_supabase

class SupabaseArtifactService:
    """Stores ADK artifacts in Supabase Storage."""

    def __init__(self, bucket_name: str = "aria-artifacts"):
        self.bucket_name = bucket_name

    async def save_artifact(
        self,
        artifact_id: str,
        content: bytes | str | Any,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Save an artifact to Supabase storage."""
        client = await get_supabase()

        if isinstance(content, str):
            content = content.encode("utf-8")
        elif not isinstance(content, bytes):
            # Try to serialize if it's some other object type,
            # though usually it's bytes or string
            import json
            content = json.dumps(content).encode("utf-8")

        # Determine Content-Type and Content-Disposition based on extension
        content_type = "application/octet-stream"
        content_disposition = None
        lower_id = artifact_id.lower()
        
        if lower_id.endswith(".html"):
            content_type = "text/html; charset=utf-8"
            content_disposition = f"attachment; filename={artifact_id}"
        elif lower_id.endswith(".pdf"):
            content_type = "application/pdf"
            content_disposition = f"inline; filename={artifact_id}"
        elif lower_id.endswith(".png"):
            content_type = "image/png"
        elif lower_id.endswith(".jpg") or lower_id.endswith(".jpeg"):
            content_type = "image/jpeg"
        elif lower_id.endswith(".json"):
            content_type = "application/json"
        elif lower_id.endswith(".csv"):
            content_type = "text/csv"

        file_options = {"upsert": "true", "content-type": content_type}
        if content_disposition:
            file_options["content-disposition"] = content_disposition

        # Upload to Supabase
        try:
            await client.storage.from_(self.bucket_name).upload(
                artifact_id, content, file_options=file_options
            )
        except Exception as e:
            err_str = str(e)
            if "Bucket not found" in err_str or "not_found" in err_str.lower() or "404" in err_str:
                try:
                    # Attempt to create the bucket programmatically with public access
                    await client.storage.create_bucket(self.bucket_name, options={"public": True})
                    # Retry the upload
                    await client.storage.from_(self.bucket_name).upload(
                        artifact_id, content, file_options={"upsert": "true"}
                    )
                except Exception:
                    raise e
            else:
                raise e

        return artifact_id

    async def get_artifact(self, artifact_id: str) -> bytes:
        """Retrieve an artifact from Supabase storage."""
        client = await get_supabase()
        response = await client.storage.from_(self.bucket_name).download(artifact_id)
        return response

    async def get_artifact_url(self, artifact_id: str) -> str:
        """Get public URL for an artifact."""
        client = await get_supabase()
        return await client.storage.from_(self.bucket_name).get_public_url(artifact_id)
