from mcp.server.fastmcp import FastMCP
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, os, re, uuid

mcp = FastMCP(
    "Project Brain",
    instructions="""
You are working in a project that uses Project Brain for engineering memory.

MANDATORY RULES — follow these before every response:
1. Call get_context() at session start — returns a slim index (IDs, titles, tags).
   If the index contains entries relevant to your task, call get_context(focus=[...])
   to load their full content before proceeding.
2. Call validate_plan(plan, current_project) BEFORE proposing any architectural or
   implementation approach. current_project is required — use the repo folder name.
   - Same project → hard conflict (must resolve before proceeding).
   - Different project → soft reference (consider, don't blindly block).
   - prior_analysis → previously stored findings relevant to the plan. If any finding
     is outdated or you now know more detail, call add_finding with the same question
     to update it before proceeding.
3. Call add_decision/add_finding/add_mistake with the current project name immediately
   when a decision is confirmed, a mistake is found, a question is answered,
   OR when you understand how a framework/library/codebase component works.
   Never wait until session end.
4. Before starting implementation, verify relevant findings still match the current
   codebase. If a stored finding is outdated or inaccurate, call add_finding again
   with the same question to update it before proceeding.
5. If add_finding returns consolidation_suggested=True, ask the user whether to
   organize findings now, then call consolidate_findings() if they agree.

These rules exist to prevent re-investigating solved problems and repeating rejected architectures.
"""
)

_default_db = Path.home() / ".project-brain" / "memory.json"
DB_PATH = Path(os.environ["PROJECT_BRAIN_MEMORY_PATH"]) if "PROJECT_BRAIN_MEMORY_PATH" in os.environ else _default_db

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def load_db() -> dict:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not DB_PATH.exists():
        empty = {"state": {"version": 1, "current_focus": [], "open_questions": [], "findings_since_review": 0},
                 "decisions": [], "findings": [], "mistakes": []}
        DB_PATH.write_text(json.dumps(empty, indent=2, ensure_ascii=False), encoding="utf-8")
        return empty
    data = json.loads(DB_PATH.read_text(encoding="utf-8"))
    data.setdefault("state", {"version": 1, "current_focus": [], "open_questions": [], "findings_since_review": 0})
    data["state"].setdefault("findings_since_review", 0)
    data.setdefault("decisions", [])
    data.setdefault("mistakes", [])
    data.setdefault("findings", [])
    return data

def save_db(data: dict):
    tmp = DB_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(DB_PATH)

def _keywords(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z0-9]+", text.lower()))

def _tag_matches(tag: str, keywords: set[str]) -> bool:
    parts = re.split(r"[-_]", tag.lower())
    norm = "".join(parts)
    if any(norm in kw for kw in keywords):
        return True
    return len(parts) > 1 and all(p in keywords for p in parts)

def _filter_by_focus(items: list[dict], keywords: set[str]) -> list[dict]:
    return [i for i in items if any(_tag_matches(t, keywords) for t in i.get("tags", []))]

def _slim(entry: dict, entry_type: str) -> dict:
    base = {
        "id":         entry["id"],
        "project":    entry.get("project", "unknown"),
        "tags":       entry.get("tags", []),
        "created_at": entry.get("created_at"),
    }
    if entry.get("updated_at"):
        base["updated_at"] = entry["updated_at"]
    if entry_type == "decisions":
        base["title"] = entry["title"]
    elif entry_type == "findings":
        base["question"] = entry["question"]
    else:
        base["description"] = entry["description"][:120]
    return base


# ── Context ───────────────────────────────────────────────────────────────────

@mcp.tool()
def get_context(focus: list[str] | None = None) -> dict:
    """Two modes:
    - No focus: returns slim index (id, title/question/description, tags, project).
      Use at session start to orient. Check which entries are relevant to your task.
    - With focus: updates current_focus and returns full content filtered by tags.
      Call this after reviewing the index when you need detail on relevant entries."""
    db = load_db()
    if focus is not None:
        db["state"]["current_focus"] = focus
        db["state"]["version"] += 1
        save_db(db)
        kw = _keywords(" ".join(focus))
        return {
            "state":     db["state"],
            "decisions": _filter_by_focus(db["decisions"], kw),
            "findings":  _filter_by_focus(db["findings"],  kw),
            "mistakes":  _filter_by_focus(db["mistakes"],  kw),
        }
    return {
        "state":     db["state"],
        "decisions": [_slim(e, "decisions") for e in db["decisions"]],
        "findings":  [_slim(e, "findings")  for e in db["findings"]],
        "mistakes":  [_slim(e, "mistakes")  for e in db["mistakes"]],
    }


# ── State ─────────────────────────────────────────────────────────────────────

@mcp.tool()
def update_open_questions(open_questions: list[str]) -> dict:
    """Replace the open_questions list. Use to track unresolved questions for future sessions."""
    db = load_db()
    db["state"]["open_questions"] = open_questions
    db["state"]["version"] += 1
    save_db(db)
    return db["state"]


# ── Decisions ─────────────────────────────────────────────────────────────────

@mcp.tool()
def add_decision(title: str, reason: str, tags: list[str], project: str = "unknown") -> dict:
    """Add or update an architectural decision (upsert by title).
    If a decision with this title already exists, updates reason/tags/project and sets updated_at.
    project: repository folder name (e.g. 'ocli', 'project-brain').
    Do not wait until session end. Tags are used for future conflict detection."""
    db = load_db()
    slug = re.sub(r"[^a-z0-9-]", "", title.lower().replace(" ", "-"))[:30]
    hash_suffix = hashlib.md5(title.encode()).hexdigest()[:8]
    entry_id = f"{slug}{hash_suffix}" if slug else hash_suffix
    for existing in db["decisions"]:
        if existing["id"] == entry_id:
            existing["reason"]     = reason
            existing["tags"]       = [t.lower() for t in tags]
            existing["project"]    = project
            existing["updated_at"] = _now()
            db["state"]["version"] += 1
            save_db(db)
            return existing
    entry = {
        "id":         entry_id,
        "project":    project,
        "title":      title,
        "reason":     reason,
        "tags":       [t.lower() for t in tags],
        "created_at": _now(),
    }
    db["decisions"].append(entry)
    db["state"]["version"] += 1
    save_db(db)
    return entry


# ── Findings ──────────────────────────────────────────────────────────────────

@mcp.tool()
def add_finding(question: str, conclusion: str, tags: list[str], project: str = "unknown") -> dict:
    """Add or update a finding (upsert by question).
    Call when an investigation question is answered, OR when you've analyzed how a
    framework/library/codebase component works — use question as the topic title in that case.
    If a finding with this question already exists, updates conclusion/tags/project.
    project: repository folder name (e.g. 'ocli', 'project-brain').
    Do not wait until session end."""
    db = load_db()
    slug = re.sub(r"[^a-z0-9-]", "", question.lower().replace(" ", "-"))[:30]
    hash_suffix = hashlib.md5(question.encode()).hexdigest()[:8]
    entry_id = f"finding-{slug}{hash_suffix}" if slug else f"finding-{hash_suffix}"
    for existing in db["findings"]:
        if existing["id"] == entry_id:
            existing["conclusion"] = conclusion
            existing["tags"]       = [t.lower() for t in tags]
            existing["project"]    = project
            existing["updated_at"] = _now()
            db["state"]["version"] += 1
            save_db(db)
            return existing
    entry = {
        "id":         entry_id,
        "project":    project,
        "question":   question,
        "conclusion": conclusion,
        "tags":       [t.lower() for t in tags],
        "created_at": _now(),
    }
    db["findings"].append(entry)
    db["state"]["findings_since_review"] += 1
    db["state"]["version"] += 1
    save_db(db)
    result = dict(entry)
    if db["state"]["findings_since_review"] >= REVIEW_THRESHOLD:
        result["consolidation_suggested"] = True
        result["consolidation_hint"] = (
            f"{db['state']['findings_since_review']} new findings since last review. "
            "Ask the user whether to organize them, then call consolidate_findings()."
        )
    return result


# ── Mistakes ──────────────────────────────────────────────────────────────────

@mcp.tool()
def add_mistake(description: str, lesson: str, tags: list[str] | None = None, project: str = "unknown") -> dict:
    """Call this immediately when a mistake or wrong approach is identified.
    project: repository folder name (e.g. 'ocli', 'project-brain').
    Do not wait until session end."""
    db = load_db()
    entry = {
        "id":          f"mistake-{uuid.uuid4().hex[:8]}",
        "project":     project,
        "description": description,
        "lesson":      lesson,
        "tags":        [t.lower() for t in (tags or [])],
        "created_at":  _now(),
    }
    db["mistakes"].append(entry)
    db["state"]["version"] += 1
    save_db(db)
    return entry


# ── Validator ─────────────────────────────────────────────────────────────────

@mcp.tool()
def validate_plan(plan: str, current_project: str) -> dict:
    """ALWAYS call this before proposing any architectural or implementation plan.
    current_project: repository folder name (e.g. 'ocli', 'project-brain') — required.
    Returns matches sorted by recency (newest first), labeled with 'project':
    - conflicts: same project — must resolve before proceeding
    - references: other projects — consider as context, don't blindly block"""
    db = load_db()
    plan_keywords = _keywords(plan)
    matches = []

    for decision in db["decisions"]:
        overlap = {tag for tag in decision["tags"] if _tag_matches(tag, plan_keywords)}
        if overlap:
            matches.append({
                "type":         "decision",
                "project":      decision.get("project", "unknown"),
                "id":           decision["id"],
                "title":        decision["title"],
                "reason":       decision["reason"],
                "matched_tags": list(overlap),
                "created_at":   decision.get("created_at", ""),
            })

    for mistake in db["mistakes"]:
        overlap = {tag for tag in mistake.get("tags", []) if _tag_matches(tag, plan_keywords)}
        if overlap:
            matches.append({
                "type":         "mistake",
                "project":      mistake.get("project", "unknown"),
                "id":           mistake["id"],
                "description":  mistake["description"],
                "lesson":       mistake["lesson"],
                "matched_tags": list(overlap),
                "created_at":   mistake.get("created_at", ""),
            })

    matches.sort(key=lambda m: m["created_at"], reverse=True)
    same  = [m for m in matches if m["project"] == current_project]
    other = [m for m in matches if m["project"] != current_project]

    prior = []
    for f in db["findings"]:
        overlap = {t for t in f.get("tags", []) if _tag_matches(t, plan_keywords)}
        if overlap:
            prior.append({
                "type":         "finding",
                "id":           f["id"],
                "project":      f.get("project", "unknown"),
                "question":     f["question"],
                "conclusion":   f["conclusion"],
                "matched_tags": list(overlap),
                "created_at":   f.get("updated_at") or f.get("created_at", ""),
            })
    prior.sort(key=lambda m: m["created_at"], reverse=True)

    return {
        "conflicts":      same,
        "references":     other,
        "prior_analysis": prior,
    }


# ── Consolidate ───────────────────────────────────────────────────────────────

@mcp.tool()
def consolidate_findings() -> dict:
    """Returns decisions and findings grouped by tag for review, then resets the counter.
    Call when consolidation_suggested is returned by add_finding and the user agrees.
    Use the grouped view to spot duplicates or outdated entries, then clean up with
    add_finding (upsert) or delete_entry. Resets findings_since_review to 0."""
    db = load_db()
    groups: dict[str, dict] = {}
    for decision in db["decisions"]:
        for tag in decision.get("tags", []):
            groups.setdefault(tag, {"decisions": [], "findings": []})
            groups[tag]["decisions"].append({
                "id": decision["id"], "title": decision["title"],
                "reason": decision["reason"], "project": decision.get("project", "unknown"),
            })
    for finding in db["findings"]:
        for tag in finding.get("tags", []):
            groups.setdefault(tag, {"decisions": [], "findings": []})
            groups[tag]["findings"].append({
                "id": finding["id"], "question": finding["question"],
                "conclusion": finding["conclusion"], "project": finding.get("project", "unknown"),
                "updated_at": finding.get("updated_at"),
            })
    db["state"]["findings_since_review"] = 0
    db["state"]["version"] += 1
    save_db(db)
    return {"groups": groups, "total_tags": len(groups)}


# ── Edit / Delete ─────────────────────────────────────────────────────────────

def _find_entry(db: dict, entry_id: str) -> tuple[str, dict] | tuple[None, None]:
    for entry_type in ("decisions", "findings", "mistakes"):
        for entry in db[entry_type]:
            if entry["id"] == entry_id:
                return entry_type, entry
    return None, None

@mcp.tool()
def update_entry(entry_id: str, updates: dict) -> dict:
    """Update fields of an existing decision, finding, or mistake by ID.
    updates: dict of fields to overwrite (e.g. {"reason": "new reason", "tags": ["a","b"]})
    Note: 'id' and 'created_at' are protected and will not be overwritten."""
    db = load_db()
    _, entry = _find_entry(db, entry_id)
    if entry is None:
        return {"error": f"id={entry_id!r} not found"}
    updates.pop("id", None)
    updates.pop("created_at", None)
    entry.update(updates)
    entry["updated_at"] = _now()
    db["state"]["version"] += 1
    save_db(db)
    return entry


@mcp.tool()
def delete_entry(entry_id: str) -> dict:
    """Delete a decision, finding, or mistake by ID.
    Use when an entry is outdated, incorrect, or no longer relevant."""
    db = load_db()
    entry_type, _ = _find_entry(db, entry_id)
    if entry_type is None:
        return {"error": f"id={entry_id!r} not found"}
    db[entry_type] = [e for e in db[entry_type] if e["id"] != entry_id]
    db["state"]["version"] += 1
    save_db(db)
    return {"deleted": entry_id}


def main():
    mcp.run()

if __name__ == "__main__":
    main()
