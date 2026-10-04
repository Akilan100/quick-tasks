"""Google Tasks API client with OAuth2 token handling and natural input parser."""

import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import dateutil.parser
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError

CONFIG_DIR = Path.home() / ".config/quick-tasks"
DEFAULT_CLIENT_SECRET = CONFIG_DIR / "client_secret.json"
DEFAULT_TOKEN_PATH = CONFIG_DIR / "token.json"

SCOPES = [
    "https://www.googleapis.com/auth/tasks"
]


def format_google_error(e: Exception) -> str:
    if isinstance(e, HttpError):
        content = e.content.decode("utf-8") if isinstance(getattr(e, "content", ""), bytes) else str(getattr(e, "content", ""))
        if "accessNotConfigured" in content or "has not been used in project" in content:
            return (
                "Google Tasks API is disabled in your Google Cloud Project.\n"
                "Enable it by visiting the Google Cloud Console for your project."
            )
        return f"Google Tasks API HTTP {getattr(e.resp, 'status', 'Error')}: {getattr(e, 'reason', str(e))}"
    return str(e)


def parse_time_component(time_str: str) -> Optional[Tuple[int, int, int]]:
    """Helper to parse time expressions like 5pm, 5:30pm, 17:00, noon, midnight."""
    if not time_str:
        return None
    time_str = time_str.strip().lower()
    time_str = re.sub(r'^(?:at\s+|@)', '', time_str).strip()
    if not time_str:
        return None

    if time_str in ("noon", "midday"):
        return 12, 0, 0
    if time_str == "midnight":
        return 23, 59, 59

    # Regex for 5pm, 5:30pm, 5.30pm, 17:00, 17.00, 9am, 12pm, 12am, etc.
    m = re.match(r'^(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?$', time_str)
    if m:
        hr = int(m.group(1))
        mn = int(m.group(2)) if m.group(2) else 0
        ampm = m.group(3)
        if ampm == 'pm' and hr < 12:
            hr += 12
        elif ampm == 'am' and hr == 12:
            hr = 0
        elif ampm is None and hr > 23:
            return None
        if 0 <= hr <= 23 and 0 <= mn <= 59:
            return hr, mn, 0

    try:
        dummy_base = datetime(2000, 1, 1, 0, 0, 0)
        parsed = dateutil.parser.parse(time_str, default=dummy_base)
        return parsed.hour, parsed.minute, parsed.second
    except Exception:
        pass
    return None


def parse_due_syntax(text: str) -> Tuple[str, Optional[str]]:
    """
    Parses quick syntax from task title with support for dates and times:
    e.g.:
      /due:today, /due:tomorrow, /due:monday
      /due:5pm, /due:17:00, /due:5:30pm
      /due:today@5pm, /due:today 5pm, /due:tomorrow at 18:00
      /due:2026-10-15, /due:2026-10-15@18:00, /due:2026-10-15 5pm
      /due:"tomorrow 5pm"
    """
    time_pattern_segment = r'(?:[\s]+(?:at\s+|@)?(?:(?:[0-1]?[0-9]|2[0-3])(?::[0-5][0-9])?\s*(?:am|pm|[ap]\.m\.)?|(?:[0-1]?[0-9]|2[0-3]):[0-5][0-9]|noon|midnight))'
    due_pattern = re.compile(
        r'/due:(?:"([^"]+)"|\'([^\']+)\'|((?:[^\s]+' + time_pattern_segment + r')|[^\s]+))',
        re.IGNORECASE
    )

    match = due_pattern.search(text)
    if not match:
        return text.strip(), None

    raw_due = match.group(1) or match.group(2) or match.group(3)
    if not raw_due:
        return text.strip(), None

    raw_due = raw_due.strip()
    cleaned_title = due_pattern.sub('', text).strip()
    cleaned_title = re.sub(r'\s+', ' ', cleaned_title)

    local_now = datetime.now().astimezone()
    today_local = local_now.date()

    pure_time = parse_time_component(raw_due)
    target_date = None

    if pure_time is not None and not any(w in raw_due.lower() for w in ['today', 'tod', 'tom', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun', '-', '/']):
        target_date = today_local.date() if isinstance(today_local, datetime) else today_local
    else:
        date_part = raw_due
        time_part = None

        m_date = re.match(r'^(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{4}[-/.]\d{1,2}[-/.]\d{1,2})[-@_\sT]+(.+)$', raw_due, re.IGNORECASE)
        if m_date:
            date_part, time_part = m_date.group(1), m_date.group(2)
        else:
            split_match = re.split(r'[@_]|\s+at\s+|\s+|T(?=\d{2}:)', raw_due, maxsplit=1, flags=re.IGNORECASE)
            if len(split_match) == 2:
                date_part, time_part = split_match[0], split_match[1]
            elif '-' in raw_due and not re.match(r'^\d{1,2}-\d{1,2}-\d{2,4}$', raw_due) and not re.match(r'^\d{4}-\d{2}-\d{2}$', raw_due):
                parts = raw_due.split('-', 1)
                if parts[0].lower() in ('today', 'tod', 'tomorrow', 'tom', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'):
                    date_part, time_part = parts[0], parts[1]

        target_date = None
        d_lower = date_part.lower().strip()

        if d_lower in ('today', 'tod'):
            target_date = today_local
        elif d_lower in ('tomorrow', 'tom'):
            target_date = today_local + timedelta(days=1)
        else:
            weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
            matched_weekday = None
            for i, w in enumerate(weekdays):
                if w.startswith(d_lower) and len(d_lower) >= 3:
                    matched_weekday = i
                    break

            if matched_weekday is not None:
                current_weekday = today_local.weekday()
                days_ahead = (matched_weekday - current_weekday) % 7
                if days_ahead == 0:
                    days_ahead = 7
                target_date = today_local + timedelta(days=days_ahead)
            else:
                try:
                    parsed = dateutil.parser.parse(date_part, default=local_now, dayfirst=True)
                    target_date = parsed.date()
                    if time_part is None and (parsed.hour != local_now.hour or parsed.minute != local_now.minute or parsed.second != local_now.second):
                        time_part = f'{parsed.hour}:{parsed.minute}:{parsed.second}'
                except Exception:
                    pass

    if target_date:
        # Google Tasks API explicitly deletes time. It expects exactly T00:00:00.000Z
        # for the ALL DAY event of that timezone.
        # Shifting timezone into UTC shifts the Date by 1 day! Avoid tz shift logic.
        iso_date = f"{target_date.strftime('%Y-%m-%d')}T00:00:00.000Z"
        return cleaned_title, iso_date
    return cleaned_title, None


class GoogleTasksClient:
    def __init__(
        self,
        client_secret_path: Optional[Path] = None,
        token_path: Optional[Path] = None
    ):
        self.client_secret_path = client_secret_path or DEFAULT_CLIENT_SECRET
        self.token_path = token_path or DEFAULT_TOKEN_PATH
        self._service: Optional[Resource] = None
        self.last_error: Optional[str] = None

    def get_credentials(self) -> Optional[Credentials]:
        if not self.token_path.exists():
            return None

        try:
            creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open(self.token_path, "w") as token_file:
                    token_file.write(creds.to_json())
            return creds if creds.valid else None
        except Exception:
            return None

    def is_authenticated(self) -> bool:
        creds = self.get_credentials()
        return creds is not None and creds.valid

    def authenticate_interactive(self, open_browser: bool = True) -> bool:
        """Launches local OAuth server flow to get user authorization."""
        if not self.client_secret_path.exists():
            raise FileNotFoundError(f"Google client secret not found at {self.client_secret_path}")

        flow = InstalledAppFlow.from_client_secrets_file(
            str(self.client_secret_path),
            scopes=SCOPES
        )
        creds = flow.run_local_server(port=0, open_browser=open_browser)
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.token_path, "w") as token_file:
            token_file.write(creds.to_json())
        os.chmod(str(self.token_path), 0o600)
        self._service = None
        return self.is_authenticated()

    @property
    def service(self) -> Resource:
        if self._service is None:
            creds = self.get_credentials()
            if not creds:
                raise RuntimeError("Not authenticated with Google Tasks. Run authenticate_interactive() first.")
            self._service = build("tasks", "v1", credentials=creds, cache_discovery=False)
        return self._service

    def verify_api_enabled(self) -> Tuple[bool, str]:
        """Probes the Google Tasks API to verify credentials and API activation."""
        if not self.is_authenticated():
            return False, "Not authenticated. Run 'quick-tasks auth' first."
        try:
            self.service.tasklists().list(maxResults=1).execute()
            self.last_error = None
            return True, "API active and connected."
        except Exception as e:
            err = format_google_error(e)
            self.last_error = err
            return False, err

    def list_all_tasks(self, show_completed: bool = True, show_hidden: bool = True) -> List[Dict[str, Any]]:
        """Queries all user task lists to sync tasks from both '@default' and custom lists."""
        if not self.is_authenticated():
            return []
        try:
            lists_res = self.service.tasklists().list(maxResults=20).execute()
            items = lists_res.get("items", [])
            if not items:
                return self.list_tasks(task_list="@default", show_completed=show_completed, show_hidden=show_hidden)

            all_tasks: List[Dict[str, Any]] = []
            seen_ids = set()
            for tlist in items:
                tasks = self.list_tasks(task_list=tlist["id"], show_completed=show_completed, show_hidden=show_hidden)
                for t in tasks:
                    if t.get("id") and t["id"] not in seen_ids:
                        seen_ids.add(t["id"])
                        all_tasks.append(t)
            self.last_error = None
            return all_tasks
        except Exception as e:
            err = format_google_error(e)
            self.last_error = err
            raise RuntimeError(err) from e

    def list_tasks(self, task_list: str = "@default", show_completed: bool = True, show_hidden: bool = True) -> List[Dict[str, Any]]:
        if not self.is_authenticated():
            return []
        try:
            result = self.service.tasks().list(
                tasklist=task_list,
                showCompleted=show_completed,
                showHidden=show_hidden,
                maxResults=100
            ).execute()
            self.last_error = None
            return result.get("items", [])
        except Exception as e:
            err = format_google_error(e)
            self.last_error = err
            print(f"[GoogleTasksClient] list_tasks error: {err}")
            raise RuntimeError(err) from e

    def create_task(
        self,
        title: str,
        notes: str = "",
        due: Optional[str] = None,
        task_list: str = "@default"
    ) -> Optional[Dict[str, Any]]:
        if not self.is_authenticated():
            return None

        body: Dict[str, Any] = {"title": title}
        if notes:
            body["notes"] = notes
        if due:
            body["due"] = due

        try:
            res = self.service.tasks().insert(tasklist=task_list, body=body).execute()
            self.last_error = None
            return res
        except Exception as e:
            err = format_google_error(e)
            self.last_error = err
            print(f"[GoogleTasksClient] create_task error: {err}")
            raise RuntimeError(err) from e

    def update_task(
        self,
        google_id: str,
        title: Optional[str] = None,
        notes: Optional[str] = None,
        due: Optional[str] = None,
        status: Optional[str] = None,
        task_list: str = "@default"
    ) -> Optional[Dict[str, Any]]:
        if not self.is_authenticated():
            return None

        try:
            current = self.service.tasks().get(tasklist=task_list, task=google_id).execute()
            if title is not None:
                current["title"] = title
            if notes is not None:
                current["notes"] = notes
            if due is not None:
                current["due"] = due
            if status is not None:
                current["status"] = status
                if status == "needsAction":
                    current["completed"] = None

            res = self.service.tasks().update(tasklist=task_list, task=google_id, body=current).execute()
            self.last_error = None
            return res
        except Exception as e:
            err = format_google_error(e)
            self.last_error = err
            print(f"[GoogleTasksClient] update_task error: {err}")
            raise RuntimeError(err) from e

    def delete_task(self, google_id: str, task_list: str = "@default") -> bool:
        if not self.is_authenticated():
            return False

        try:
            self.service.tasks().delete(tasklist=task_list, task=google_id).execute()
            self.last_error = None
            return True
        except Exception as e:
            if isinstance(e, HttpError) and e.resp.status == 404:
                # If 404, the task is already deleted on Google Tasks (idempotent success)
                self.last_error = None
                return True
            err = format_google_error(e)
            self.last_error = err
            print(f"[GoogleTasksClient] delete_task error: {err}")
            raise RuntimeError(err) from e
