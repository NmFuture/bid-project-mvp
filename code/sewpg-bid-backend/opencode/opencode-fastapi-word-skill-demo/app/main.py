from __future__ import annotations

import asyncio
import json
import os
import shutil
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
JOBS_DIR = DATA_DIR / "jobs"
DEFAULT_SKILL = os.environ.get("OPENCODE_DEFAULT_SKILL", "officecli")
OPENCODE_BIN = os.environ.get("OPENCODE_BIN", shutil.which("opencode") or "opencode")


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class CreateJobFromPathRequest(BaseModel):
    input_path: str = Field(..., description="Absolute path to the source .docx file")
    task: str = Field(..., description="What OpenCode should do to the document")
    skill_name: str = Field(DEFAULT_SKILL, description="Installed OpenCode skill to use")
    yolo: bool = Field(True, description="Whether to enable --dangerously-skip-permissions")
    output_filename: str = Field("output.docx", description="Name of the generated .docx artifact")


class JobRecord(BaseModel):
    id: str
    status: JobStatus
    created_at: str
    updated_at: str
    finished_at: Optional[str] = None
    source_mode: str
    skill_name: str
    task: str
    yolo: bool
    workdir: str
    input_path: str
    output_path: str
    output_filename: str
    prompt_path: str
    logs_path: str
    command: List[str]
    pid: Optional[int] = None
    result_text: Optional[str] = None
    error: Optional[str] = None


app = FastAPI(
    title="OpenCode Word Skill Demo",
    description="Background FastAPI wrapper around `opencode run` for DOCX processing.",
    version="0.1.0",
)

job_tasks: Dict[str, asyncio.Task] = {}
job_lock = asyncio.Lock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dirs() -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)


def job_dir(job_id: str) -> Path:
    return JOBS_DIR / job_id


def job_file(job_id: str) -> Path:
    return job_dir(job_id) / "job.json"


def sanitize_filename(filename: str, default_name: str) -> str:
    candidate = Path(filename or default_name).name.strip() or default_name
    if not candidate.lower().endswith(".docx"):
        candidate = f"{candidate}.docx"
    return candidate


def is_docx_filename(filename: Optional[str]) -> bool:
    return bool(filename) and Path(filename).suffix.lower() == ".docx"


def load_job(job_id: str) -> JobRecord:
    path = job_file(job_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return JobRecord(**json.loads(path.read_text(encoding="utf-8")))


async def save_job(job: JobRecord) -> None:
    async with job_lock:
        path = job_file(job.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(job.dict(), ensure_ascii=False, indent=2)
        path.write_text(payload, encoding="utf-8")


def list_jobs() -> List[JobRecord]:
    ensure_dirs()
    records: List[JobRecord] = []
    for path in JOBS_DIR.glob("*/job.json"):
        try:
            records.append(JobRecord(**json.loads(path.read_text(encoding="utf-8"))))
        except Exception:
            continue
    records.sort(key=lambda item: item.created_at, reverse=True)
    return records


def write_prompt(prompt_path: Path, prompt: str) -> None:
    prompt_path.write_text(prompt, encoding="utf-8")


def build_prompt(skill_name: str, input_path: Path, output_path: Path, task: str) -> str:
    return "\n".join(
        [
            f"Use the {skill_name} skill.",
            f'The source Word file is at "{input_path}".',
            f'The output Word file must be written to "{output_path}".',
            "You must produce a valid .docx file at the output path.",
            "Do not ask the user for clarification unless the task is impossible to complete.",
            "Keep the final chat response short and include the final output path.",
            "",
            "Task:",
            task,
        ]
    )


def prepare_path_input(job_id: str, source_path: Path) -> Path:
    input_dir = job_dir(job_id) / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    link_path = input_dir / source_path.name
    if link_path.exists() or link_path.is_symlink():
        link_path.unlink()
    try:
        link_path.symlink_to(source_path)
        return link_path
    except OSError:
        return source_path


async def save_uploaded_file(upload: UploadFile, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as handle:
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
    await upload.close()


def build_job(
    job_id: str,
    input_path: Path,
    task: str,
    skill_name: str,
    yolo: bool,
    output_filename: str,
    source_mode: str,
) -> JobRecord:
    current_job_dir = job_dir(job_id)
    output_dir = current_job_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = current_job_dir / "prompt.txt"
    logs_path = current_job_dir / "opencode.log"
    output_name = sanitize_filename(output_filename, "output.docx")
    output_path = output_dir / output_name
    prompt = build_prompt(skill_name=skill_name, input_path=input_path, output_path=output_path, task=task)
    write_prompt(prompt_path, prompt)

    command = [
        OPENCODE_BIN,
        "run",
        "--format",
        "json",
        "--dir",
        str(current_job_dir),
    ]
    if yolo:
        command.append("--dangerously-skip-permissions")
    command.append(prompt)

    now = utc_now()
    return JobRecord(
        id=job_id,
        status=JobStatus.queued,
        created_at=now,
        updated_at=now,
        source_mode=source_mode,
        skill_name=skill_name,
        task=task,
        yolo=yolo,
        workdir=str(current_job_dir),
        input_path=str(input_path),
        output_path=str(output_path),
        output_filename=output_name,
        prompt_path=str(prompt_path),
        logs_path=str(logs_path),
        command=command,
    )


async def stream_pipe(stream: asyncio.StreamReader, log_path: Path, result_parts: List[str]) -> None:
    with log_path.open("a", encoding="utf-8") as log_file:
        while True:
            raw = await stream.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            log_file.write(line + "\n")
            log_file.flush()
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "text":
                part = event.get("part") or {}
                text = part.get("text")
                if text:
                    result_parts.append(text)


async def run_job(job_id: str) -> None:
    job = load_job(job_id)
    logs_path = Path(job.logs_path)
    logs_path.parent.mkdir(parents=True, exist_ok=True)
    result_parts: List[str] = []

    job.status = JobStatus.running
    job.updated_at = utc_now()
    await save_job(job)

    try:
        process = await asyncio.create_subprocess_exec(
            *job.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        job.status = JobStatus.failed
        job.updated_at = utc_now()
        job.finished_at = job.updated_at
        job.error = f"OpenCode binary not found: {OPENCODE_BIN}"
        await save_job(job)
        return

    job.pid = process.pid
    job.updated_at = utc_now()
    await save_job(job)

    await asyncio.gather(
        stream_pipe(process.stdout, logs_path, result_parts),
        stream_pipe(process.stderr, logs_path, result_parts),
    )
    return_code = await process.wait()

    output_path = Path(job.output_path)
    job.updated_at = utc_now()
    job.finished_at = job.updated_at
    job.result_text = "\n".join(result_parts).strip() or None

    if return_code != 0:
        job.status = JobStatus.failed
        job.error = f"OpenCode exited with code {return_code}"
    elif not output_path.exists():
        job.status = JobStatus.failed
        job.error = "OpenCode finished without producing the expected .docx artifact"
    else:
        job.status = JobStatus.succeeded
        job.error = None

    await save_job(job)


def start_job(job: JobRecord) -> None:
    task = asyncio.create_task(run_job(job.id))
    job_tasks[job.id] = task


def validate_input_docx(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=400, detail=f"Input file does not exist: {resolved}")
    if resolved.suffix.lower() != ".docx":
        raise HTTPException(status_code=400, detail="Only .docx input is supported in this demo")
    return resolved


def require_job_artifact(job: JobRecord) -> Path:
    artifact = Path(job.output_path)
    if not artifact.exists():
        raise HTTPException(status_code=404, detail="Artifact is not available yet")
    return artifact


@app.on_event("startup")
async def startup_event() -> None:
    ensure_dirs()


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "opencode_bin": OPENCODE_BIN,
        "opencode_found": Path(OPENCODE_BIN).exists() if os.path.isabs(OPENCODE_BIN) else bool(shutil.which(OPENCODE_BIN)),
        "jobs_dir": str(JOBS_DIR),
    }


@app.get("/jobs", response_model=List[JobRecord])
async def get_jobs() -> List[JobRecord]:
    return list_jobs()


@app.get("/jobs/{job_id}", response_model=JobRecord)
async def get_job(job_id: str) -> JobRecord:
    return load_job(job_id)


@app.get("/jobs/{job_id}/logs", response_class=PlainTextResponse)
async def get_job_logs(job_id: str) -> PlainTextResponse:
    job = load_job(job_id)
    log_path = Path(job.logs_path)
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="Logs are not available yet")
    return PlainTextResponse(log_path.read_text(encoding="utf-8"))


@app.get("/jobs/{job_id}/artifact")
async def get_job_artifact(job_id: str) -> FileResponse:
    job = load_job(job_id)
    artifact = require_job_artifact(job)
    return FileResponse(
        path=artifact,
        filename=job.output_filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@app.post("/jobs/from-path", response_model=JobRecord, status_code=202)
async def create_job_from_path(request: CreateJobFromPathRequest) -> JobRecord:
    ensure_dirs()
    source_path = validate_input_docx(Path(request.input_path))
    job_id = uuid4().hex[:12]
    prepared_input = prepare_path_input(job_id, source_path)
    job = build_job(
        job_id=job_id,
        input_path=prepared_input,
        task=request.task,
        skill_name=request.skill_name,
        yolo=request.yolo,
        output_filename=request.output_filename,
        source_mode="path",
    )
    await save_job(job)
    start_job(job)
    return job


@app.post("/jobs/upload", response_model=JobRecord, status_code=202)
async def create_job_from_upload(
    file: UploadFile = File(...),
    task: str = Form(...),
    skill_name: str = Form(DEFAULT_SKILL),
    yolo: bool = Form(True),
    output_filename: str = Form("output.docx"),
) -> JobRecord:
    ensure_dirs()
    if not is_docx_filename(file.filename):
        raise HTTPException(status_code=400, detail="Only .docx input is supported in this demo")
    original_name = sanitize_filename(file.filename or "input.docx", "input.docx")

    job_id = uuid4().hex[:12]
    input_path = job_dir(job_id) / "input" / original_name
    await save_uploaded_file(file, input_path)
    job = build_job(
        job_id=job_id,
        input_path=input_path,
        task=task,
        skill_name=skill_name,
        yolo=yolo,
        output_filename=output_filename,
        source_mode="upload",
    )
    await save_job(job)
    start_job(job)
    return job
