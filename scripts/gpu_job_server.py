#!/usr/bin/env python3
"""
GPU Job Server - Runs on the PC (pop-os), accepts job requests from the Pi.

This is the PC-side component. It runs an HTTP server that the Pi can call
to dispatch GPU jobs. It handles:
- Job submission (Python scripts to run)
- GPU memory management
- Status reporting
- Graceful error handling

Run on PC: python3 gpu_job_server.py [--port 8765]
"""

import http.server
import json
import subprocess
import sys
import os
import threading
import time
import traceback
import tempfile
import uuid


PORT = 8765
jobs = {}  # job_id -> job_result
jobs_lock = threading.Lock()


def get_gpu_status():
    """Get current GPU status."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            parts = [p.strip() for p in result.stdout.strip().split(",")]
            return {
                "name": parts[0],
                "memory_total": parts[1],
                "memory_used": parts[2],
                "memory_free": parts[3],
                "utilization": parts[4],
                "temperature": parts[5] if len(parts) > 5 else "N/A"
            }
    except Exception:
        pass
    return None


def run_python_script(script_content, job_id):
    """Run a Python script with GPU access. Returns (success, stdout, stderr)."""
    # Write script to temp file
    script_path = os.path.join(tempfile.gettempdir(), f"gpu_job_{job_id}.py")
    with open(script_path, "w") as f:
        f.write(script_content)

    try:
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            timeout=600  # 10 minute timeout
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "Job timed out after 10 minutes"
    except Exception as e:
        return False, "", str(e)
    finally:
        # Clean up
        try:
            os.remove(script_path)
        except Exception:
            pass


class JobHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        """Suppress default logging for cleaner output."""
        pass

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        if self.path == "/status":
            gpu = get_gpu_status()
            self._send_json({
                "status": "online",
                "gpu": gpu,
                "python": sys.version,
                "hostname": os.uname().nodename
            })
        elif self.path == "/jobs":
            with jobs_lock:
                self._send_json({"jobs": jobs})
        elif self.path.startswith("/job/"):
            job_id = self.path.split("/job/")[-1]
            with jobs_lock:
                job = jobs.get(job_id)
            if job:
                self._send_json(job)
            else:
                self._send_json({"error": "Job not found"}, 404)
        else:
            self._send_json({
                "endpoints": {
                    "/status": "GET - PC + GPU status",
                    "/jobs": "GET - List all jobs",
                    "/job/<id>": "GET - Get job result",
                    "/submit": "POST - Submit a Python script to run on GPU"
                }
            })

    def do_POST(self):
        if self.path == "/submit":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)

            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self._send_json({"error": "Invalid JSON"}, 400)
                return

            script = data.get("script", "")
            if not script:
                self._send_json({"error": "No script provided"}, 400)
                return

            job_id = str(uuid.uuid4())[:8]

            # Run job in background thread
            def run_job():
                with jobs_lock:
                    jobs[job_id] = {
                        "id": job_id,
                        "status": "running",
                        "started": time.time()
                    }

                try:
                    success, stdout, stderr = run_python_script(script, job_id)
                    with jobs_lock:
                        jobs[job_id] = {
                            "id": job_id,
                            "status": "completed" if success else "failed",
                            "success": success,
                            "stdout": stdout[-10000:] if len(stdout) > 10000 else stdout,  # Cap output
                            "stderr": stderr[-5000:] if len(stderr) > 5000 else stderr,
                            "started": jobs[job_id]["started"],
                            "finished": time.time()
                        }
                except Exception as e:
                    with jobs_lock:
                        jobs[job_id] = {
                            "id": job_id,
                            "status": "failed",
                            "error": str(e),
                            "started": jobs[job_id]["started"],
                            "finished": time.time()
                        }

            thread = threading.Thread(target=run_job, daemon=True)
            thread.start()

            self._send_json({
                "job_id": job_id,
                "status": "submitted",
                "message": f"Job {job_id} submitted. Check /job/{job_id} for results."
            })

        else:
            self._send_json({"error": "Unknown endpoint"}, 404)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    server = http.server.HTTPServer(("0.0.0.0", port), JobHandler)
    print(f"GPU Job Server running on port {port}")
    print(f"Endpoints: http://0.0.0.0:{port}/status")
    print(f"           http://0.0.0.0:{port}/submit")
    print("Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
