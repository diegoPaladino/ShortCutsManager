import os
import json
import subprocess
import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox
from datetime import datetime
from collections import defaultdict

DATA_FILE = "usage_data.json"
REPORT_FOLDER = "reports"

class SmartLauncher:
    def __init__(self, root):
        self.root = root
        self.root.title("Smart Launcher - Eficiência Neural")
        self.root.geometry("800x600")
        self.root.configure(bg="#1e1e1e")

        os.makedirs(REPORT_FOLDER, exist_ok=True)

        self.data = self.load_data()

        self.frame = tk.Frame(self.root, bg="#1e1e1e")
        self.frame.pack(fill="both", expand=True)

        self.render_buttons()
        self.render_controls()

    def load_data(self):
        if not os.path.exists(DATA_FILE):
            return {"shortcuts": {}}
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_data(self):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=4)

    def get_current_week(self):
        now = datetime.now()
        return f"{now.year}-W{now.strftime('%U')}"

    def execute_shortcut(self, name):
        path = self.data["shortcuts"][name]["path"]
        try:
            subprocess.Popen(path, shell=True)
            self.update_usage(name)
        except Exception as e:
            messagebox.showerror("Erro", str(e))

    def update_usage(self, name):
        week = self.get_current_week()
        shortcut = self.data["shortcuts"][name]

        shortcut["total_clicks"] += 1

        if "weekly_clicks" not in shortcut:
            shortcut["weekly_clicks"] = {}

        shortcut["weekly_clicks"][week] = shortcut["weekly_clicks"].get(week, 0) + 1

        self.save_data()

    def add_shortcut(self):
        name = simpledialog.askstring("Novo Atalho", "Nome do botão:")
        if not name:
            return

        file_path = filedialog.askopenfilename()
        if not file_path:
            return

        self.data["shortcuts"][name] = {
            "path": file_path,
            "total_clicks": 0,
            "weekly_clicks": {}
        }

        self.save_data()
        self.refresh_ui()

    def generate_report(self):
        week = self.get_current_week()
        report_data = []

        for name, info in self.data["shortcuts"].items():
            weekly = info.get("weekly_clicks", {})
            count = weekly.get(week, 0)
            report_data.append((name, count))

        report_data.sort(key=lambda x: x[1], reverse=True)

        report_text = f"Relatório da Semana {week}\n\n"

        report_text += "Mais Utilizados:\n"
        for name, count in report_data[:5]:
            report_text += f"{name}: {count}\n"

        report_text += "\nMenos Utilizados:\n"
        for name, count in report_data[-5:]:
            report_text += f"{name}: {count}\n"

        report_path = os.path.join(REPORT_FOLDER, f"report_{week}.txt")

        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_text)

        messagebox.showinfo("Relatório Gerado", report_text)

    def render_buttons(self):
        for widget in self.frame.winfo_children():
            widget.destroy()

        row = 0
        col = 0

        for name in self.data["shortcuts"]:
            btn = tk.Button(
                self.frame,
                text=name,
                width=20,
                height=3,
                bg="#2d2d2d",
                fg="white",
                command=lambda n=name: self.execute_shortcut(n)
            )
            btn.grid(row=row, column=col, padx=10, pady=10)

            col += 1
            if col >= 4:
                col = 0
                row += 1

    def render_controls(self):
        control_frame = tk.Frame(self.root, bg="#121212")
        control_frame.pack(fill="x")

        add_btn = tk.Button(
            control_frame,
            text="Adicionar Atalho",
            command=self.add_shortcut,
            bg="#007acc",
            fg="white",
            height=2
        )
        add_btn.pack(side="left", padx=10, pady=5)

        report_btn = tk.Button(
            control_frame,
            text="Gerar Relatório Semanal",
            command=self.generate_report,
            bg="#28a745",
            fg="white",
            height=2
        )
        report_btn.pack(side="right", padx=10, pady=5)

    def refresh_ui(self):
        self.render_buttons()

if __name__ == "__main__":
    root = tk.Tk()
    app = SmartLauncher(root)
    root.mainloop()