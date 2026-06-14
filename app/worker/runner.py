"""Run lifecycle: clone -> branch -> run graph -> (graph finalizes PR) -> cleanup.

`process_job` is the async callable the JobQueue invokes per job. It prepares an
isolated workspace, builds the run context + graph (bound to the shared Postgres
checkpointer), drives it to completion, and cleans up.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil

from app.config import get_settings
from app.graph.builder import build_graph
from app.logging_config import set_run_id
from app.models import Job, RunContext
from app.tools import git_tools
from app.tools.github_tools import GitHubClient

log = logging.getLogger(__name__)


def _slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (slug[:max_len].strip("-")) or "task"


def _make_processor(checkpointer):
    async def process_job(job: Job) -> None:
        await _process_job(job, checkpointer)

    return process_job


async def _process_job(job: Job, checkpointer) -> None:
    cfg = get_settings()
    set_run_id(job.run_id)
    log.info("starting run for %s#%d: %s", job.full_name, job.issue_number, job.issue_title)

    branch = f"ai-task/issue-{job.issue_number}-{_slugify(job.issue_title)}"
    workspace = os.path.join(cfg.workspace_root, f"{job.repo}-{job.run_id}")
    os.makedirs(cfg.workspace_root, exist_ok=True)

    github = GitHubClient(job.owner, job.repo)

    try:
        await asyncio.to_thread(
            github.add_issue_comment,
            job.issue_number,
            f"🤖 **Coordinator3000** picked up this `{cfg.ai_task_label}` issue "
            f"(run `{job.run_id}`). Working on branch `{branch}`…",
        )

        await asyncio.to_thread(
            git_tools.clone_repo, job.clone_url, workspace, job.base_branch
        )
        await asyncio.to_thread(git_tools.create_branch, workspace, branch)

        ctx = RunContext(
            run_id=job.run_id,
            owner=job.owner,
            repo=job.repo,
            issue_number=job.issue_number,
            issue_title=job.issue_title,
            issue_body=job.issue_body,
            base_branch=job.base_branch,
            branch=branch,
            workspace=workspace,
            clone_url=job.clone_url,
        )

        graph = build_graph(ctx, github, checkpointer)
        config = {
            "configurable": {
                "thread_id": f"{job.full_name}#{job.issue_number}:{job.run_id}"
            },
            "recursion_limit": 50,
        }
        final = await graph.ainvoke({"iterations": 0, "status": "running"}, config=config)
        log.info(
            "run %s finished: status=%s pr=%s",
            job.run_id,
            final.get("status"),
            final.get("pr_url"),
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("run %s failed", job.run_id)
        try:
            await asyncio.to_thread(
                github.add_issue_comment,
                job.issue_number,
                f"🤖 **Coordinator3000** hit an error on run `{job.run_id}` and "
                f"could not finish:\n\n```\n{exc}\n```",
            )
        except Exception:  # noqa: BLE001
            log.warning("could not post failure comment")
    finally:
        github.close()
        shutil.rmtree(workspace, ignore_errors=True)
        log.info("cleaned workspace %s", workspace)
