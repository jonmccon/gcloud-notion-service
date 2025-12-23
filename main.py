import os
import re
import requests
from datetime import datetime, timedelta, timezone
from typing import Optional

from google.auth import default
from googleapiclient.discovery import build

# ----------------------------
# Constants
# ----------------------------

NOTION_API_URL = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

TASK_TYPE_REGEX = re.compile(r'^([A-Za-z]{3,5})-\s?')
CLEANUP_DAYS = 7

# ----------------------------
# Helpers
# ----------------------------

def now_utc():
    return datetime.now(timezone.utc)


def parse_rfc3339(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def extract_task_type(title: str) -> Optional[str]:
    match = TASK_TYPE_REGEX.match(title or "")
    return match.group(1).upper() if match else None


def normalize_title(title: str) -> str:
    return TASK_TYPE_REGEX.sub("", title).strip()


# ----------------------------
# Google Tasks
# ----------------------------

def google_service():
    creds, _ = default()
    return build("tasks", "v1", credentials=creds)


def get_google_tasks() -> list[dict]:
    service = google_service()
    tasks = []

    tasklists = service.tasklists().list().execute().get("items", [])
    for tasklist in tasklists:
        result = service.tasks().list(
            tasklist=tasklist["id"],
            showCompleted=True,
            showHidden=True
        ).execute()

        for task in result.get("items", []):
            task["tasklist_id"] = tasklist["id"]
            tasks.append(task)

    return tasks


def complete_google_task(task: dict):
    service = google_service()
    service.tasks().patch(
        tasklist=task["tasklist_id"],
        task=task["id"],
        body={"status": "completed"}
    ).execute()


# ----------------------------
# Notion Helpers
# ----------------------------

def notion_headers():
    return {
        "Authorization": f"Bearer {os.environ['NOTION_API_KEY']}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def find_notion_task(google_task_id: str) -> Optional[dict]:
    response = requests.post(
        f"{NOTION_API_URL}/databases/{os.environ['NOTION_DB_ID']}/query",
        headers=notion_headers(),
        json={
            "filter": {
                "property": "Google Task ID",
                "rich_text": {"equals": google_task_id}
            }
        },
        timeout=10,
    )
    response.raise_for_status()
    results = response.json().get("results", [])
    return results[0] if results else None


def create_notion_task(task: dict):
    raw_title = task.get("title", "Untitled")
    task_type = extract_task_type(raw_title)

    properties = {
        "Task name": {
            "title": [{"text": {"content": normalize_title(raw_title)}}]
        },
        "Status": {
            "status": {
                "name": "Completed" if task.get("status") == "completed" else "To do"
            }
        },
        "Google Task ID": {
            "rich_text": [{"text": {"content": task["id"]}}]
        },
        "Imported at": {
            "date": {"start": now_utc().isoformat()}
        },
        "Updated at": {
            "date": {"start": task.get("updated")}
        } if task.get("updated") else None,
        "Due date": {
            "date": {"start": task.get("due")}
        } if task.get("due") else None,
        "Description": {
            "rich_text": [{"text": {"content": task.get("notes")}}]
        } if task.get("notes") else None,
        "Link": {"url": task.get("selfLink")},
        "Effort level": {"select": {"name": "Medium"}},
    }

    if task_type:
        properties["Task type"] = {
            "multi_select": [{"name": task_type}]
        }

    properties = {k: v for k, v in properties.items() if v is not None}

    requests.post(
        f"{NOTION_API_URL}/pages",
        headers=notion_headers(),
        json={
            "parent": {"database_id": os.environ["NOTION_DB_ID"]},
            "properties": properties,
        },
        timeout=10,
    ).raise_for_status()


def update_notion_task(page_id: str, task: dict):
    properties = {
        "Task name": {
            "title": [{"text": {"content": normalize_title(task["title"])}}]
        },
        "Updated at": {
            "date": {"start": task.get("updated")}
        } if task.get("updated") else None,
        "Due date": {
            "date": {"start": task.get("due")}
        } if task.get("due") else None,
        "Description": {
            "rich_text": [{"text": {"content": task.get("notes")}}]
        } if task.get("notes") else None,
    }

    properties = {k: v for k, v in properties.items() if v is not None}

    requests.patch(
        f"{NOTION_API_URL}/pages/{page_id}",
        headers=notion_headers(),
        json={"properties": properties},
        timeout=10,
    ).raise_for_status()


# ----------------------------
# Main Sync Logic
# ----------------------------

def sync_tasks(request):
    tasks = get_google_tasks()
    created = updated = completed = 0

    for task in tasks:
        if task.get("deleted"):
            continue

        notion_page = find_notion_task(task["id"])

        if not notion_page:
            create_notion_task(task)
            created += 1
            continue

        # Incremental update
        notion_updated = notion_page["properties"].get("Updated at", {}) \
            .get("date", {}) \
            .get("start")

        if notion_updated and task.get("updated"):
            if parse_rfc3339(task["updated"]) > parse_rfc3339(notion_updated):
                update_notion_task(notion_page["id"], task)
                updated += 1

        # Weekly cleanup
        imported_at = notion_page["properties"]["Imported at"]["date"]["start"]
        if now_utc() - parse_rfc3339(imported_at) > timedelta(days=CLEANUP_DAYS):
            if task.get("status") != "completed":
                complete_google_task(task)
                completed += 1

    return {
        "status": "ok",
        "created": created,
        "updated": updated,
        "completed_in_google": completed,
        "total_seen": len(tasks),
    }
