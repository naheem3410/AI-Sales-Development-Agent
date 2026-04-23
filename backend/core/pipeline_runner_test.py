"""Manual test harness for pipeline_runner — run from sda_platform root."""

import asyncio

from backend.core.pipeline_runner import PipelineRunner


async def main():
    runner = PipelineRunner()
    await runner.run_full_pipeline(
        user_id="97a8e1d6-f52c-45fd-8405-6f242485654c",
        campaign_name="Lapo Campaign",
        website_url="https://www.lapo-nigeria.org/",
        company_name="Lapo",
    )


if __name__ == "__main__":
    asyncio.run(main())
