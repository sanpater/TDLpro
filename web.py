import os
import sys
import psutil
from flask import Flask, jsonify, send_file, request
import threading
from config import user_tasks
from core.flowapi import get_flowvideo_links

app = Flask(__name__)

@app.route("/")
def health_check():
    return jsonify({"running": True, "thread_alive": True})

@app.route("/logs")
def view_logs():
    if os.path.exists("bot.log"):
        # Serve the log file as text
        return send_file("bot.log", mimetype="text/plain")
    else:
        return "Log file not found.", 404

@app.route("/diagnostics")
def system_diagnostics():
    cpu_usage = psutil.cpu_percent(interval=1)
    ram = psutil.virtual_memory()
    disk = psutil.disk_usage('/')

    # Calculate total active tasks
    active_tasks = sum(len(tasks) for tasks in user_tasks.values())

    return jsonify({
        "status": "healthy",
        "system": {
            "cpu_percent": cpu_usage,
            "ram_total_mb": round(ram.total / (1024 * 1024), 2),
            "ram_used_mb": round(ram.used / (1024 * 1024), 2),
            "ram_percent": ram.percent,
            "disk_total_gb": round(disk.total / (1024**3), 2),
            "disk_used_gb": round(disk.used / (1024**3), 2),
            "disk_percent": disk.percent
        },
        "bot": {
            "active_downloads": active_tasks
        }
    })

@app.route("/restart", methods=["POST"])
def restart_bot():
    """
    Restart the bot programmatically.
    Warning: This uses os.execv to replace the current process.
    It is useful if the bot gets stuck.
    """
    def restart():
        python = sys.executable
        os.execl(python, python, *sys.argv)

    # Start the restart process in a new thread so we can return the response first
    threading.Timer(2.0, restart).start()
    return jsonify({"status": "restarting in 2 seconds..."})

def start_server():
    # Hugging Face spaces use port 7860
    app.run(host="0.0.0.0", port=7860, debug=False, use_reloader=False)

def run_web_server():
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    return server_thread
