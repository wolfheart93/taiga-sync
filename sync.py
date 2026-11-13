"""
Sets each Taiga user story's status from its tasks' statuses.
Runs once and exits; GitHub Actions runs it on a schedule.

Rules (checked top to bottom, first match wins):
  1. any task  Testing         -> story Testing
  2. any task  In progress     -> story In progress
  3. all tasks Done            -> story Ready for live
  4. all tasks Ready for test  -> story Ready for test
  otherwise (or no tasks)      -> story left unchanged
Stories already in Live or Complete are never changed.
"""
import os
import sys
from collections import defaultdict

import requests

API = "https://api.taiga.io/api/v1"
PROJECT_SLUG = "doruk-masters-of-madness-30"

ANY_RULES = [                    # one matching task is enough
    ("Testing", "Testing"),
    ("In progress", "In progress"),
]
# Stories in these statuses are never touched
PROTECTED_STATUSES = {"Live", "Complete"}

ALL_RULES = [                    # every task must match
    ("Done", "Ready for live"),
    ("Ready for test", "Ready for test"),
]


def target_status(names):
    for task_status, story_status in ANY_RULES:
        if task_status in names:
            return story_status
    for task_status, story_status in ALL_RULES:
        if all(n == task_status for n in names):
            return story_status
    return None


def main():
    s = requests.Session()
    r = s.post(f"{API}/auth", json={
        "type": "normal",
        "username": os.environ["TAIGA_USERNAME"],
        "password": os.environ["TAIGA_PASSWORD"],
    })
    if r.status_code != 200:
        sys.exit(f"Login failed ({r.status_code}). Check TAIGA_USERNAME / TAIGA_PASSWORD.")
    s.headers["Authorization"] = f"Bearer {r.json()['auth_token']}"
    s.headers["x-disable-pagination"] = "True"

    project = s.get(f"{API}/projects/by_slug", params={"slug": PROJECT_SLUG}).json()
    pid = project["id"]

    story_status_ids = {st["name"]: st["id"] for st in
                        s.get(f"{API}/userstory-statuses", params={"project": pid}).json()}
    for _, name in ANY_RULES + ALL_RULES:
        if name not in story_status_ids:
            sys.exit(f"Story status '{name}' does not exist in the project. "
                     f"Existing: {', '.join(story_status_ids)}")

    tasks_by_story = defaultdict(list)
    for t in s.get(f"{API}/tasks", params={"project": pid}).json():
        if t.get("user_story"):
            tasks_by_story[t["user_story"]].append(t["status_extra_info"]["name"])

    changed = 0
    for us_id, names in tasks_by_story.items():
        wanted = target_status(names)
        if wanted is None:
            continue
        story = s.get(f"{API}/userstories/{us_id}").json()
        if story["status_extra_info"]["name"] in PROTECTED_STATUSES:
            continue
        if story["status"] == story_status_ids[wanted]:
            continue
        r = s.patch(f"{API}/userstories/{us_id}", json={
            "status": story_status_ids[wanted], "version": story["version"]})
        if r.ok:
            changed += 1
            print(f"#{story['ref']} {story['subject']!r}: "
                  f"{story['status_extra_info']['name']} -> {wanted}")
        else:
            print(f"#{story['ref']}: update failed ({r.status_code}), will retry next run")

    print(f"Done. {changed} story(s) updated.")


if __name__ == "__main__":
    main()
