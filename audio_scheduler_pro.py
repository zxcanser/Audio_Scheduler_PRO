import tkinter as tk
from tkinter import filedialog, messagebox
import schedule
import time
import threading
import os
import json
from datetime import datetime
import pystray
from pystray import MenuItem as item
from PIL import Image, ImageDraw
import sys
import sounddevice as sd
import soundfile as sf
import numpy as np

CONFIG_FILE = "config.json"
SCHEDULE_FILE = "schedule.json"
LOG_FILE = "log.txt"


class AudioSchedulerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Audio Scheduler PRO")
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)

        self.schedule_data = {}
        self.selected_device = None
        self.load_schedule()

        self.file_path = tk.StringVar()
        self.time_str = tk.StringVar()
        self.volume = tk.DoubleVar(value=0.8)

        self.playing_thread = None

        self.build_ui()
        self.start_scheduler()
        self.create_tray_icon()

    # ================= UI =================

    def build_ui(self):
        tk.Label(self.root, text="Аудиофайл:").grid(row=0, column=0)
        tk.Entry(self.root, textvariable=self.file_path, width=40).grid(row=0, column=1)
        tk.Button(self.root, text="Выбрать", command=self.browse_file, width=10, height=1).grid(row=0, column=2)

        tk.Label(self.root, text="Время (ЧЧ:ММ):").grid(row=1, column=0)

        # Поле для ввода часов
        self.hours_var = tk.StringVar()
        self.hours_entry = tk.Entry(self.root, textvariable=self.hours_var, width=2)
        self.hours_entry.place(x=108, y=25)

        # Двоеточие между часами и минутами
        tk.Label(self.root, text=":").place(x=123, y=25)

        # Поле для ввода минут
        self.minutes_var = tk.StringVar()
        self.minutes_entry = tk.Entry(self.root, textvariable=self.minutes_var, width=2)
        self.minutes_entry.place(x=130, y=25)

        #tk.Entry(self.root, textvariable=self.time_str, width=10).place(x=108, y=25)

        tk.Button(self.root, text="Добавить", command=self.add_schedule, width=10, height=1).grid(row=1, column=2)

        self.listbox = tk.Listbox(self.root, width=70)
        self.listbox.grid(row=3, column=0, columnspan=3)

        tk.Button(self.root, text="Удалить", command=self.delete_schedule, width=10, height=1).grid(row=4, column=2)

        self.root.bind("<Return>", self.add_schedule_from_key)  # Enter
        self.root.bind("<Delete>", self.delete_schedule_from_key)  # Delete

        tk.Button(self.root, text="Прослушать", command=self.test_play, width=10, height=1).grid(row=4, column=0)
        tk.Button(self.root, text="Стоп", command=self.stop_audio, width=10, height=1).grid(row=5, column=0)

        tk.Label(self.root, text="Громкость").grid(row=5, column=1)
        tk.Scale(self.root, from_=0, to=1, resolution=0.1,
                 orient="horizontal", variable=self.volume).grid(row=4, column=1)

        # ===== Выбор аудио устройства =====
        tk.Label(self.root, text="Аудио-интерфейс:").grid(row=6, column=0)
        self.device_var = tk.StringVar()
        self.device_menu = tk.OptionMenu(self.root, self.device_var, "")
        self.device_menu.grid(row=6, column=1)

        tk.Button(self.root, text="Обновить устройства", command=self.load_devices).grid(row=6, column=2)

        self.load_device()
        self.load_devices()
        self.update_listbox()

    def browse_file(self):
        file = filedialog.askopenfilename(filetypes=[("Audio Files", "*.wav;*.mp3;*.flac;*.ogg")])
        if file:
            self.file_path.set(file)


    # ================= Аудио устройства =================

    def load_devices(self):
        devices = sd.query_devices()
        output_devices = [d for d in devices if d['max_output_channels'] > 0]

        menu = self.device_menu["menu"]
        menu.delete(0, "end")

        for d in output_devices:
            name = d['name']
            menu.add_command(label=name,
                             command=lambda value=name: self.device_var.set(value))

        if output_devices:
            self.device_var.set(self.selected_device if self.selected_device else output_devices[0]['name'])

    def load_device(self):
        """Загружаем выбранное устройство из конфигурации"""
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
                self.selected_device = config.get("selected_device")

    def save_device(self):
        """Сохраняем выбранное устройство в конфигурацию"""
        config = {
            "selected_device": self.device_var.get()
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f)

    def on_device_change(self, event=None):
        """Сохраняем устройство при изменении"""
        self.selected_device = self.device_var.get()
        self.save_device()

    # ================= Планировщик =================

    def add_schedule(self):
        # Получаем значения часов и минут
        hour = self.hours_var.get()
        minute = self.minutes_var.get()

        # Проверяем, если час или минута пусты
        if not hour or not minute:
            messagebox.showerror("Ошибка", "Пожалуйста, выберите время")
            return

        # Проверяем, что час и минуты содержат только цифры
        if not hour.isdigit() or not minute.isdigit():
            messagebox.showerror("Ошибка", "Время должно быть в формате HH:MM")
            return

        # Создаём строку времени в формате HH:MM
        time_value = f"{hour.zfill(2)}:{minute.zfill(2)}"

        file = self.file_path.get()

        if not file:
            messagebox.showerror("Ошибка", "Файл не найден")
            return

        self.schedule_data[time_value] = file
        self.save_schedule()
        self.register_jobs()
        self.update_listbox()

    def delete_schedule(self):
        selected = self.listbox.curselection()
        if selected:
            time_value = self.listbox.get(selected).split(" - ")[0]
            del self.schedule_data[time_value]
            self.save_schedule()
            self.register_jobs()
            self.update_listbox()

    def add_schedule_from_key(self, event):
        """Добавление записи при нажатии Enter"""
        self.add_schedule()

    def delete_schedule_from_key(self, event):
        """Удаление записи при нажатии Delete"""
        self.delete_schedule()

    def update_listbox(self):
        self.listbox.delete(0, tk.END)
        for t, f in sorted(self.schedule_data.items()):
            filename = os.path.basename(f)  # Извлекаем имя файла
            self.listbox.insert(tk.END, f"{t} - {filename}")

    # ================= Воспроизведение =================
    
    def play_notification_sound(self):
        """Воспроизводим звук уведомления перед основным действием"""
        notification_sound_file = "notification_sound.mp3"  # Путь к вашему файлу уведомления
        try:
            data, samplerate = sf.read(notification_sound_file, dtype='float32')
            data *= self.volume.get()

            sd.play(data, samplerate)
            sd.wait()  # Дождитесь завершения воспроизведения
        except Exception as e:
            print(f"Ошибка при воспроизведении уведомления: {e}")


    def play_audio(self, file):
        self.play_notification_sound()

        try:
            device_name = self.device_var.get()
            devices = sd.query_devices()

            device_id = None
            for i, d in enumerate(devices):
                if d['name'] == device_name:
                    device_id = i
                    break

            data, samplerate = sf.read(file, dtype='float32')
            data *= self.volume.get()

            sd.play(data, samplerate, device=device_id)
            sd.wait()

            self.write_log(f"Played: {file} on {device_name}")

        except Exception as e:
            self.write_log(f"Error: {e}")

    def stop_audio(self):
        if self.playing_thread and self.playing_thread.is_alive():
            sd.stop()  # Останавливаем воспроизведение
            self.write_log("Audio stopped")

    def test_play(self):
        file = self.file_path.get()

        # Если файл не выбран в поле, то используем файл из списка
        if not file:
            selected = self.listbox.curselection()
            if selected:
                time_value = self.listbox.get(selected).split(" - ")[0]
                file = self.schedule_data.get(time_value)

        if file and os.path.exists(file):
            self.playing_thread = threading.Thread(target=self.play_audio, args=(file,), daemon=True)
            self.playing_thread.start()
        else:
            messagebox.showerror("Ошибка", "Файл не найден")

    # ================= Scheduler loop =================

    def register_jobs(self):
        schedule.clear()
        for t, f in self.schedule_data.items():
            schedule.every().day.at(t).do(
                lambda file=f: threading.Thread(
                    target=self.play_audio, args=(file,), daemon=True
                ).start()
            )

    def scheduler_loop(self):
        while True:
            schedule.run_pending()
            time.sleep(1)

    def start_scheduler(self):
        self.register_jobs()
        threading.Thread(target=self.scheduler_loop, daemon=True).start()

    # ================= Логи и файлы =================

    def write_log(self, text):
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now()} - {text}\n")

    def save_schedule(self):
        with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.schedule_data, f)

    def load_schedule(self):
        if os.path.exists(SCHEDULE_FILE):
            with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
                self.schedule_data = json.load(f)

    # ================= Трей =================

    def hide_window(self):
        self.root.withdraw()

    def show_window(self, icon, item):
        self.root.after(0, self.root.deiconify)

    def quit_app(self, icon, item):
        self.save_device()
        icon.stop()
        self.root.destroy()
        sys.exit()

    def create_image(self):
        img = Image.new('RGB', (64, 64), color='blue')
        d = ImageDraw.Draw(img)
        d.rectangle((16, 16, 48, 48), fill='white')
        return img

    def create_tray_icon(self):
        menu = (item('Открыть', self.show_window),
                item('Выход', self.quit_app))
        icon = pystray.Icon("AudioScheduler", self.create_image(),
                            "Audio Scheduler PRO", menu)
        threading.Thread(target=icon.run, daemon=True).start()


if __name__ == "__main__":
    root = tk.Tk()
    app = AudioSchedulerApp(root)
    root.mainloop()
