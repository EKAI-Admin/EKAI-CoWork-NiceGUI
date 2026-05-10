"""Background run manager — executes CoWorker runs independent of page navigation."""

import asyncio
import logging
from functools import partial
from pathlib import Path

from nicegui import background_tasks

from db import (
    start_run,
    get_settings,
    create_run_record,
    update_run_progress,
    update_run_status,
    get_active_run_for_coworker,
    is_run_cancelling,
)


class _RunCancelled(Exception):
    """Raised internally when a run is cancelled by user request."""
from ai_runner import (
    prepare_run,
    process_single_file,
    finalize_run,
    load_skill_manifest,
    run_skill_pipeline,
)

log = logging.getLogger(__name__)


async def _to_thread(func, *args, **kwargs):
    """Run a blocking function in the default executor (not tied to any client)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(func, *args, **kwargs))


async def _execute_run(run_id: int, coworker: dict, user_id: int):
    """Background coroutine that executes a full coworker run.

    Updates DB progress at each step so any page can poll status.
    """
    script_log = ""
    try:
        update_run_status(run_id, "running")
        update_run_progress(run_id, "Preparing inputs...")

        # Create run folder and copy files
        run_dir, copied = await _to_thread(start_run, coworker["name"])
        update_run_progress(
            run_id,
            f"Preparing {len(copied)} file(s)...",
            run_dir=str(run_dir),
            files_total=len(copied),
        )

        # Load prompt and skills
        prompt, files, skills_context = await _to_thread(prepare_run, run_dir)

        settings = get_settings(user_id)
        ollama_url = settings["ollama_base_url"] if settings else "http://localhost:11434"
        provider = coworker["model_provider"]
        model = coworker["model_name"]

        # Process each file through AI
        file_results = []
        for i, f in enumerate(files):
            if is_run_cancelling(run_id):
                raise _RunCancelled()
            update_run_progress(
                run_id,
                f"Processing file {i + 1}/{len(files)}: {f['name']}",
                files_processed=i,
            )
            try:
                result = await _to_thread(
                    process_single_file, provider, model, prompt, f, skills_context, ollama_url,
                )
            except Exception as file_err:
                if "rate_limit" in str(file_err).lower() or "429" in str(file_err):
                    update_run_progress(
                        run_id,
                        f"Rate limited on file {i + 1}/{len(files)}, retrying...",
                    )
                    result = await _to_thread(
                        process_single_file, provider, model, prompt, f, skills_context, ollama_url,
                    )
                else:
                    raise
            file_results.append(result)

        if is_run_cancelling(run_id):
            raise _RunCancelled()

        # Finalize — write result.md
        update_run_progress(run_id, "Writing results...", files_processed=len(files))
        output_file = await _to_thread(
            finalize_run, run_dir, coworker["name"], provider, model, files, file_results,
        )

        # Skill pipeline
        manifest = load_skill_manifest(run_dir)
        produced_files: list[Path] = []
        script_log = ""
        if manifest:
            skill_name = manifest.get("name", "skill")
            update_run_progress(run_id, f"Running skill pipeline: {skill_name}...")
            try:
                produced_files, script_log = await _to_thread(
                    run_skill_pipeline, run_dir, manifest, provider, model, files, ollama_url,
                )
            except Exception as script_err:
                log.warning("Skill pipeline error for run %s: %s", run_id, script_err)
                update_run_progress(run_id, f"Skill pipeline error: {script_err}")
                # Still try to capture partial log from the error message
                script_log = f"Pipeline failed: {script_err}"

        # Mark complete
        pdf_files = [str(p) for p in produced_files if p.suffix == ".pdf"]
        msg = f"Done — {len(files)} file(s) analyzed"
        if produced_files:
            msg += " + skill pipeline complete"
        update_run_status(
            run_id,
            "completed",
            files_processed=len(files),
            has_report=1,
            pdf_files=pdf_files,
            run_dir=str(run_dir),
            progress_message=msg,
            script_log=script_log,
        )
        log.info("Run %s completed: %s", run_id, msg)

    except _RunCancelled:
        log.info("Run %s cancelled by user", run_id)
        update_run_status(
            run_id,
            "failed",
            error="Cancelled by user",
            progress_message="Cancelled by user",
        )
    except Exception as exc:
        log.exception("Run %s failed", run_id)
        update_run_status(
            run_id,
            "failed",
            error=str(exc),
            progress_message=f"Failed: {exc}",
            script_log=script_log,
        )


class CoWorkerSuspendedError(Exception):
    """Raised when attempting to run a suspended CoWorker."""


def launch_run(coworker: dict, user_id: int) -> int | None:
    """Start a background run for the given coworker.

    Returns the new run_id, or None if a run is already active.
    Raises CoWorkerSuspendedError if the coworker is suspended.
    """
    # Refuse to run suspended CoWorkers
    if (coworker.get("status") or "").lower() == "suspended":
        raise CoWorkerSuspendedError(
            f"{coworker['name']} is suspended. Activate the CoWorker to run it."
        )

    # Prevent duplicate runs
    active = get_active_run_for_coworker(coworker["id"])
    if active:
        return None

    run_id = create_run_record(
        coworker_id=coworker["id"],
        coworker_name=coworker["name"],
        user_id=user_id,
        model_provider=coworker["model_provider"],
        model_name=coworker["model_name"],
        workflow=coworker.get("workflow", ""),
    )

    background_tasks.create(_execute_run(run_id, coworker, user_id))
    return run_id
