import requests
import json, os, sys
from pathlib import Path
from datetime import datetime
from db.db_events import *


def upload_to_supabase(url, key):
    base_folder = Path(get_sync_folder())
    headers = {
        'apikey': key,
        'Authorization': f"Bearer {key}",
        'Content-Type': 'application/json',
        'Prefer': 'resolution=merge-duplicates'

    }

    def _failed_dir():
        dir_path = base_folder / 'failed' / datetime.now().strftime('%d-%m-%Y')
        dir_path.mkdir(parents=True, exist_ok=True)
        return dir_path

    def _append_event(kind, payload):
        event = {'timestamp': datetime.now().isoformat(), 'kind': kind}
        event.update(payload)
        log_file = _failed_dir() / 'upload_events.json'
        try:
            if log_file.exists():
                with open(log_file, 'r', encoding='utf-8') as f:
                    events = json.load(f)
            else:
                events = []
        except Exception:
            events = []
        events.append(event)
        try:
            with open(log_file, 'w', encoding='utf-8') as f:
                json.dump(events, f, indent=2)
        except Exception:
            pass

    def endpoint(table):
        return f"{url}/rest/v1/{table}"

    def upload_logs(total_uploaded, total_failed, **extra):
        upload_record = {
            'user_id': 'guest',
            'uploaded_at': datetime.now().isoformat(),
            'records_uploaded': total_uploaded,
            'folder': str(base_folder),
            'failed': total_failed,
            **extra,
        }
        try:
            tracking_endpoint = endpoint('upload_logs')
            resp = requests.post(tracking_endpoint, json=upload_record, headers=headers)
            _append_event('upload_logs_response', {'status_code': resp.status_code})
        except Exception as e:
            _append_event('upload_logs_exception', {'error': str(e)})


    def _normalize_ts(ts):
        if not isinstance(ts, str):
            return ts
        return ts.replace('T', ' ').replace('Z', '+00')

    def _normalize_record_datetimes(rec: dict):
        if not isinstance(rec, dict):
            return rec
        out = {}
        for k, v in rec.items():
            if isinstance(v, dict):
                out[k] = _normalize_record_datetimes(v)
            elif isinstance(v, list):
                out[k] = [ _normalize_record_datetimes(x) if isinstance(x, dict) else x for x in v ]
            elif k in ('timestamp', 'createdAt', 'updatedAt', 'deletedAt') and isinstance(v, str):
                out[k] = _normalize_ts(v)
            else:
                out[k] = v
        return out

    flattened_logs = []
    for file in base_folder.rglob('*.json'):
        # Skip logs inside failed directory
        if 'failed' in file.parts:
            continue
        try:
            with open(file, 'r', encoding="utf-8") as f:
                logs = json.load(f)
                for log in logs:
                    if isinstance(log, list):
                        flattened_logs.extend(log)
                    else:
                        flattened_logs.append(log)
        except Exception as e:
            _append_event('read_file_exception', {'file': str(file), 'error': str(e)})

    only_uploaded_data = []
    count, refused = 0, 0
    for log in flattened_logs:
        record = _normalize_record_datetimes(log.get('data', {}))
        action = str(log.get('action', 'insert')).lower()
        table = log.get('table')
        try:
            if action == 'update':
                rec_id = record.get('id')
                if rec_id is None:
                    raise ValueError(f"Update requires id for table {table}")
                url_q = f"{endpoint(table)}?id=eq.{rec_id}"
                response = requests.patch(url_q, json=record, headers=headers)
            elif action == 'delete':
                rec_id = record.get('id')
                if rec_id is None:
                    raise ValueError(f"Delete requires id for table {table}")
                url_q = f"{endpoint(table)}?id=eq.{rec_id}"
                response = requests.delete(url_q, headers=headers)
            else:  # default insert
                response = requests.post(endpoint(table), json=record, headers=headers)

            if response.status_code not in (200, 201, 204):
                refused += 1
                try:
                    details = response.json()
                except Exception:
                    details = response.text
                details_payload = {"response": details, "record": record, "table": table, "action": action}
                upload_logs(count, refused, details=details_payload)

                # Write failed record file
                try:
                    timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S%f')[:-3]
                    failed_file_name = f"failed_{table}_{timestamp_str}.json"
                    failed_file_path = _failed_dir() / failed_file_name
                    failed_record = {
                        'timestamp': datetime.now().isoformat(),
                        'table': table,
                        'action': action,
                        'record': record,
                        'response': details,
                    }
                    with open(failed_file_path, 'w', encoding='utf-8') as f:
                        json.dump(failed_record, f, indent=2)
                    _append_event('record_upload_failed', {'file': str(failed_file_path), 'table': table, 'response': details})
                except Exception as e:
                    _append_event('failed_record_write_exception', {'error': str(e)})
            else:
                count += 1
                only_uploaded_data.append({'table': table, 'action': action, 'data': record})
        except Exception as e:
            refused += 1
            _append_event('upload_exception', {'error': str(e), 'table': table, 'action': action})
    upload_logs(count, refused, status='DONE')

    _append_event('upload_summary', {'total_uploaded': count, 'total_failed': refused, 'status': 'DONE'})

    return count, only_uploaded_data
