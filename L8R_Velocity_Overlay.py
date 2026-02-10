import ctypes
import tkinter as tk
from tkinter import ttk
from ctypes import wintypes
import sys
import math
import time
import struct
import threading
import queue
import re
from collections import deque

# ==============================================================================
#  L8R SK8R VELOCITY OVERLAY
# ==============================================================================

# --- Configuration ------------------------------------------------------------

PROCESS_NAME = "l8rsk8r.exe"
BASE_MODULE = "UnityPlayer.dll" 

# Fallback Static Pointer (May not work on all PCs)
BASE_OFFSET = 0x01C67AE8
POINTER_OFFSETS = [0x100, 0xD0, 0x8, 0x48, 0x288, 0x0] 

# AOB Signature Scanning (Preferred)
# Set VELOCITY_SIGNATURE to a unique byte pattern found in Cheat Engine.
# Example: "48 8B 05 ?? ?? ?? ?? 48 8B 88"
# Use '??' for wildcards.
VELOCITY_SIGNATURE = None 
VELOCITY_SIG_OFFSET = 0x0 # Offset from the signature match to the pointer

OFFSET_VELOCITY = 0x24C
OFFSET_GRAVITY = 0x27C

# ------------------------------------------------------------------------------

# --- Windows API Definitions ---
kernel32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32

TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400

class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_char * 260)
    ]

class MODULEENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("GlblcntUsage", wintypes.DWORD),
        ("ProccntUsage", wintypes.DWORD),
        ("modBaseAddr", ctypes.c_void_p),
        ("modBaseSize", wintypes.DWORD),
        ("hModule", ctypes.c_void_p),
        ("szModule", ctypes.c_char * 256),
        ("szExePath", ctypes.c_char * 260)
    ]

def get_pid_by_name(process_name):
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    pid = None
    entry = PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
    
    if kernel32.Process32First(snapshot, ctypes.byref(entry)):
        while True:
            try:
                exe_name = entry.szExeFile.decode('utf-8').lower()
                if process_name.lower() in exe_name:
                    pid = entry.th32ProcessID
                    break
            except:
                pass
            if not kernel32.Process32Next(snapshot, ctypes.byref(entry)):
                break
    kernel32.CloseHandle(snapshot)
    return pid

def get_module_base(pid, module_name):
    try:
        snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
        if snapshot == -1 or snapshot == 0: return None, 0
    except:
        return None, 0

    base_addr = None
    base_size = 0
    entry = MODULEENTRY32()
    entry.dwSize = ctypes.sizeof(MODULEENTRY32)
    
    if kernel32.Module32First(snapshot, ctypes.byref(entry)):
        while True:
            try:
                m_name = entry.szModule.decode('utf-8').lower()
                if module_name.lower() == m_name:
                    base_addr = entry.modBaseAddr
                    base_size = entry.modBaseSize
                    break
            except:
                pass
            if not kernel32.Module32Next(snapshot, ctypes.byref(entry)):
                break
    kernel32.CloseHandle(snapshot)
    return base_addr, base_size

class MemoryReader:
    def __init__(self):
        self.pid = None
        self.handle = None
        self.modules = {}

    def attach(self, process_name):
        pid = get_pid_by_name(process_name)
        if pid:
            self.pid = pid
            self.handle = kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
            return True
        return False

    def get_module(self, module_name):
        if not self.pid: return 0, 0
        return get_module_base(self.pid, module_name)

    def read_bytes(self, address, size):
        if not self.handle or not address: return None
        buf = ctypes.create_string_buffer(size)
        read = ctypes.c_size_t()
        if kernel32.ReadProcessMemory(self.handle, ctypes.c_void_p(address), buf, size, ctypes.byref(read)):
            return buf.raw
        return None

    def read_ptr(self, address):
        data = self.read_bytes(address, 8) # 64-bit pointer
        if data:
            return struct.unpack('<Q', data)[0]
        return 0

    def read_float(self, address):
        data = self.read_bytes(address, 4)
        if data:
            return struct.unpack('<f', data)[0]
        return 0.0

    def scan_pattern(self, module_name, pattern_str):
        if not self.pid: return None
        base, size = self.get_module(module_name)
        if not base or not size: return None
        
        try:
            # Read entire module
            data = self.read_bytes(base, size)
            if not data: return None
            
            # Convert pattern "48 8B ??" -> regex
            parts = pattern_str.split()
            regex_parts = []
            for part in parts:
                if part == '??' or part == '?':
                    regex_parts.append(b'.')
                else:
                    regex_parts.append(re.escape(bytes.fromhex(part)))
            regex = b''.join(regex_parts)
            
            match = re.search(regex, data)
            if match:
                return base + match.start()
        except Exception as e:
            # print(f"Scan error: {e}")
            pass
        return None

    def resolve_chain(self, base_addr, offsets):
        current_addr = self.read_ptr(base_addr)
        if not current_addr: return 0
        
        for i, offset in enumerate(offsets):
            current_addr = self.read_ptr(current_addr + offset)
            if not current_addr:
                return 0
        return current_addr

class VelocityOverlay:
    def __init__(self, root):
        self.root = root
        self.root.title("L8R Velocity")
        self.root.attributes('-topmost', True)
        self.root.attributes('-alpha', 0.8)
        self.root.overrideredirect(True)
        # Position only, let size be dynamic
        self.root.geometry("+50+50")
        self.root.configure(bg='black')

        # --- Settings ---
        self.show_magnitude = tk.BooleanVar(value=True)
        self.show_vectors = tk.BooleanVar(value=True)
        self.show_graph = tk.BooleanVar(value=True) # Overall graph toggle

        self.graph_show_mag = tk.BooleanVar(value=True)
        self.graph_show_x = tk.BooleanVar(value=False)
        self.graph_show_y = tk.BooleanVar(value=False)
        self.graph_show_z = tk.BooleanVar(value=False)
        
        self.font_size_mag = tk.IntVar(value=24)
        self.font_size_vec = tk.IntVar(value=10)
        self.font_size_peak = tk.IntVar(value=8)
        
        self.peak_update_rate = tk.DoubleVar(value=2.0)
        self.polling_rate = tk.IntVar(value=50) # Polling rate in ms
        self.peak_display_delay = tk.IntVar(value=0) # Delay in ms
        
        self.precision_mag = tk.IntVar(value=2)
        self.precision_vec = tk.IntVar(value=2)
        self.precision_peak = tk.IntVar(value=1)
        
        self.graph_height = tk.IntVar(value=100) # Dynamic graph height

        # Apply font updates
        def update_fonts(*args):
            self.label_speed.config(font=("Consolas", self.font_size_mag.get(), "bold"))
            vec_font = ("Consolas", self.font_size_vec.get())
            self.label_vx.config(font=vec_font)
            self.label_vy.config(font=vec_font)
            self.label_vz.config(font=vec_font)
            self.draw_graph() # Redraw for peak font size

        try:
            self.show_magnitude.trace_add("write", lambda *args: self.refresh_layout())
            self.show_vectors.trace_add("write", lambda *args: self.refresh_layout())
            self.show_graph.trace_add("write", lambda *args: self.refresh_layout())
            
            self.font_size_mag.trace_add("write", update_fonts)
            self.font_size_vec.trace_add("write", update_fonts)
            self.font_size_peak.trace_add("write", lambda *args: self.draw_graph())
            self.peak_update_rate.trace_add("write", lambda *args: self.draw_graph())
            self.graph_height.trace_add("write", lambda *args: self.refresh_layout()) # Update layout if height changes
            
            self.graph_show_mag.trace_add("write", lambda *args: self.refresh_layout())
            self.graph_show_x.trace_add("write", lambda *args: self.refresh_layout())
            self.graph_show_y.trace_add("write", lambda *args: self.refresh_layout())
            self.graph_show_z.trace_add("write", lambda *args: self.refresh_layout())
        except AttributeError:
            # Fallback for older python
            pass

        # --- Data ---
        self.history = deque()
        self.history_duration = 30.0 # seconds

        # --- UI Components ---
        self.label_speed = tk.Label(root, text="WAITING...", font=("Consolas", 24, "bold"), fg="#00FF00", bg="black")
        
        self.frame_vec = tk.Frame(root, bg="black")
        self.label_vx = tk.Label(self.frame_vec, text="X: 0.00", font=("Consolas", 10), fg="#FF5555", bg="black")
        self.label_vx.pack(side="left", expand=True)
        self.label_vy = tk.Label(self.frame_vec, text="Y: 0.00", font=("Consolas", 10), fg="#55FF55", bg="black")
        self.label_vy.pack(side="left", expand=True)
        self.label_vz = tk.Label(self.frame_vec, text="Z: 0.00", font=("Consolas", 10), fg="#5555FF", bg="black")
        self.label_vz.pack(side="left", expand=True)
        
        # Multiple Canvases
        self.canvas_mag = tk.Canvas(root, bg="black", height=100, highlightthickness=0)
        self.canvas_x = tk.Canvas(root, bg="black", height=100, highlightthickness=0)
        self.canvas_y = tk.Canvas(root, bg="black", height=100, highlightthickness=0)
        self.canvas_z = tk.Canvas(root, bg="black", height=100, highlightthickness=0)
        
        self.label_status = tk.Label(root, text="Searching for game...", font=("Arial", 8), fg="white", bg="black")

        self.refresh_layout()

        self.menu = tk.Menu(root, tearoff=0)
        self.menu.add_checkbutton(label="Show Magnitude", variable=self.show_magnitude)
        self.menu.add_checkbutton(label="Show Vectors", variable=self.show_vectors)
        self.menu.add_checkbutton(label="Show Graph", variable=self.show_graph)
        self.menu.add_separator()
        self.menu.add_command(label="Settings...", command=self.open_settings)
        self.menu.add_separator()
        self.menu.add_command(label="Exit", command=sys.exit)

        self.root.bind("<ButtonPress-1>", self.start_move)
        self.root.bind("<B1-Motion>", self.do_move)
        self.root.bind("<Button-3>", self.show_context_menu)
        self.root.bind("<Double-Button-1>", lambda e: sys.exit())

        # Threading setup
        self.data_queue = queue.Queue()
        self.status_msg = "Initializing..."
        self.running = True
        self.thread_poll_rate = self.polling_rate.get()
        
        # Update thread rate when UI changes
        self.polling_rate.trace_add("write", lambda *args: setattr(self, 'thread_poll_rate', self.polling_rate.get()))

        self.mem = MemoryReader()
        self.attached = False
        self.player_address = 0
        
        # Start polling thread
        self.poll_thread = threading.Thread(target=self.polling_loop, daemon=True)
        self.poll_thread.start()
        
        self.update_ui()

    def show_context_menu(self, event):
        self.menu.post(event.x_root, event.y_root)
        
    def open_settings(self):
        settings_win = tk.Toplevel(self.root)
        settings_win.title("Settings")
        settings_win.geometry("320x450")
        settings_win.configure(bg="#222222")
        settings_win.attributes('-topmost', True)
        
        style = ttk.Style()
        style.theme_use('clam')
        
        # Create Scrollable Frame
        main_frame = tk.Frame(settings_win, bg="#222222")
        main_frame.pack(fill="both", expand=True)
        
        canvas = tk.Canvas(main_frame, bg="#222222", highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg="#222222")
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # Helper functions use scrollable_frame as parent
        def create_scale(label, var, from_, to_):
            frame = tk.Frame(scrollable_frame, bg="#222222")
            frame.pack(fill="x", padx=10, pady=5)
            tk.Label(frame, text=label, fg="white", bg="#222222").pack(anchor="w")
            scale = tk.Scale(frame, from_=from_, to=to_, orient="horizontal", variable=var, 
                             bg="#222222", fg="white", highlightthickness=0)
            scale.pack(fill="x")
            
        def create_check(label, var):
            cb = tk.Checkbutton(scrollable_frame, text=label, variable=var, bg="#222222", fg="white", 
                                selectcolor="#444444", activebackground="#222222", activeforeground="white")
            cb.pack(anchor="w", padx=10)

        # Font Settings
        lbl_fonts = tk.Label(scrollable_frame, text="Font Sizes", fg="#AAAAAA", bg="#222222", font=("Arial", 10, "bold"))
        lbl_fonts.pack(anchor="w", padx=5, pady=(10, 0))
        create_scale("Magnitude Font", self.font_size_mag, 10, 72)
        create_scale("Vectors Font", self.font_size_vec, 8, 32)
        create_scale("Graph Peak Font", self.font_size_peak, 6, 20)
        
        # Update Rate
        lbl_rate = tk.Label(scrollable_frame, text="Update Rates", fg="#AAAAAA", bg="#222222", font=("Arial", 10, "bold"))
        lbl_rate.pack(anchor="w", padx=5, pady=(10, 0))
        create_scale("Top Speed Update (sec)", self.peak_update_rate, 0.1, 10.0)
        create_scale("Poll Rate (ms)", self.polling_rate, 1, 500)
        create_scale("Peak Delay (ms)", self.peak_display_delay, 0, 2000)
        
        # Precision Settings
        lbl_prec = tk.Label(scrollable_frame, text="Decimal Precision", fg="#AAAAAA", bg="#222222", font=("Arial", 10, "bold"))
        lbl_prec.pack(anchor="w", padx=5, pady=(10, 0))
        create_scale("Magnitude Decimals", self.precision_mag, 0, 5)
        create_scale("Vectors Decimals", self.precision_vec, 0, 5)
        create_scale("Graph Peak Decimals", self.precision_peak, 0, 5)
        
        # Graph Visibility
        lbl_graph = tk.Label(scrollable_frame, text="Graphs", fg="#AAAAAA", bg="#222222", font=("Arial", 10, "bold"))
        lbl_graph.pack(anchor="w", padx=5, pady=(10, 0))
        create_scale("Graph Height", self.graph_height, 50, 300)
        create_check("Show Magnitude (Green)", self.graph_show_mag)
        create_check("Show X (Red)", self.graph_show_x)
        create_check("Show Y (Light Green)", self.graph_show_y)
        create_check("Show Z (Blue)", self.graph_show_z)
        
        # Add some padding at the bottom
        tk.Label(scrollable_frame, text="", bg="#222222").pack(pady=10)
        
        # Mousewheel scrolling
        def on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
        canvas.bind_all("<MouseWheel>", on_mousewheel)
        settings_win.bind("<Destroy>", lambda e: canvas.unbind_all("<MouseWheel>"))


    def refresh_layout(self):
        self.label_speed.pack_forget()
        self.frame_vec.pack_forget()
        self.canvas_mag.pack_forget()
        self.canvas_x.pack_forget()
        self.canvas_y.pack_forget()
        self.canvas_z.pack_forget()
        self.label_status.pack_forget()
        
        current_height = self.graph_height.get()

        if self.show_magnitude.get():
            self.label_speed.pack(pady=(10, 0))
        
        if self.show_vectors.get():
            self.frame_vec.pack(fill="x", pady=5)
            
        if self.show_graph.get():
            # Only pack individual graphs if enabled
            if self.graph_show_mag.get():
                self.canvas_mag.config(height=current_height)
                self.canvas_mag.pack(fill="x", pady=2, padx=5)
            if self.graph_show_x.get():
                self.canvas_x.config(height=current_height)
                self.canvas_x.pack(fill="x", pady=2, padx=5)
            if self.graph_show_y.get():
                self.canvas_y.config(height=current_height)
                self.canvas_y.pack(fill="x", pady=2, padx=5)
            if self.graph_show_z.get():
                self.canvas_z.config(height=current_height)
                self.canvas_z.pack(fill="x", pady=2, padx=5)
            
        self.label_status.pack(side="bottom")

    def start_move(self, event):
        self.root.x = event.x
        self.root.y = event.y

    def do_move(self, event):
        x = self.root.winfo_x() + (event.x - self.root.x)
        y = self.root.winfo_y() + (event.y - self.root.y)
        self.root.geometry(f"+{x}+{y}")
        
    def draw_single_graph(self, canvas, data_index, color, title):
        canvas.delete("all")
        
        if len(self.history) < 2: return

        width = canvas.winfo_width()
        height = canvas.winfo_height()
        if width <= 1: width = 240
        
        # Increased margin to accommodate 3 rows of labels
        margin_bottom = 40 
        graph_height = height - margin_bottom

        # Create local copy for analysis
        data = list(self.history)
        now = data[-1][0]
        start_time = now - self.history_duration
        
        # Collect values
        all_values = [d[data_index] for d in data]
        
        if not all_values: return

        max_val = max(all_values)
        min_val = min(all_values)
        
        # Adjust scale to always include 0
        if min_val > 0: min_val = 0
        if max_val < 0: max_val = 0
        
        val_range = max_val - min_val
        if val_range < 10.0: val_range = 10.0 # Minimum range
        
        # Draw Title
        canvas.create_text(2, 2, anchor="nw", text=title, fill=color, font=("Arial", 8, "bold"))
        
        # 2. Draw Grid
        # Zero line
        zero_y = graph_height - ((0 - min_val) / val_range * graph_height)
        canvas.create_line(0, zero_y, width, zero_y, fill="#555555")
        
        # Grid lines
        grid_interval = 10.0
        # Positive grid
        curr = 0
        while curr < max_val:
            y = graph_height - ((curr - min_val) / val_range * graph_height)
            if y >= 0 and y <= graph_height:
                canvas.create_line(0, y, width, y, fill="#333333", dash=(4, 4))
            curr += grid_interval
            
        # Negative grid
        curr = -10.0
        while curr > min_val:
            y = graph_height - ((curr - min_val) / val_range * graph_height)
            if y >= 0 and y <= graph_height:
                canvas.create_line(0, y, width, y, fill="#333333", dash=(4, 4))
            curr -= grid_interval
            
        canvas.create_text(width - 2, 2, anchor="ne", text=f"{max_val:.1f}", fill="#555555", font=("Arial", 8))
        canvas.create_text(width - 2, graph_height - 10, anchor="se", text=f"{min_val:.1f}", fill="#555555", font=("Arial", 8))

        # Plot Line
        points = []
        for item in data:
            t = item[0]
            val = item[data_index]
            if t < start_time: continue
            x = (t - start_time) / self.history_duration * width
            y = graph_height - ((val - min_val) / val_range * graph_height)
            points.append(x)
            points.append(y)
        if len(points) >= 4:
            canvas.create_line(points, fill=color, width=2)
            
        # Draw Peaks
        peaks = []
        for i in range(1, len(data) - 1):
            t = data[i][0]
            s = data[i][data_index] # Use relevant index
            prev_s = data[i-1][data_index]
            next_s = data[i+1][data_index]
            
            # Simple peak detection: local maxima
            # Only consider positive peaks for now, or abs magnitude?
            # User wants peaks for "max speeds". For Vectors, maybe just positive?
            # Or absolute max?
            # Let's do raw value peaks.
            if s > prev_s and s > next_s:
                 # Check threshold to avoid noise
                 if abs(s) > 1.0:
                    peaks.append((t, s))
        
        peaks.sort(key=lambda x: x[1], reverse=True)
        
        selected_peaks = []
        update_rate = self.peak_update_rate.get()
        delay_ms = self.peak_display_delay.get()
        delay_s = delay_ms / 1000.0
        
        current_time = now if now else time.time()
        
        for p in peaks:
            t, s = p
            # Skip if peak is too recent (delay)
            if (current_time - t) < delay_s:
                continue
            
            conflict = False
            for sp in selected_peaks:
                if abs(t - sp[0]) < update_rate: 
                    conflict = True
                    break
            if not conflict:
                selected_peaks.append(p)
        
        # Sort by TIME ascending to stabilize row assignment
        selected_peaks.sort(key=lambda x: x[0])
        
        peak_font = ("Arial", self.font_size_peak.get(), "bold")
        peak_decimals = self.precision_peak.get()
        
        # Only show peaks visible in window
        visible_peaks = [p for p in selected_peaks if p[0] >= start_time]
        
        for i, p in enumerate(visible_peaks):
            t, s = p
            
            px = (t - start_time) / self.history_duration * width
            py = graph_height - ((s - min_val) / val_range * graph_height)
            
            canvas.create_line(px, py, px, graph_height, fill="#FFFF00", dash=(2, 4))
            
            # Stagger labels across 3 rows to prevent overlap
            # Use stable index based on time-sorted list
            row = i % 3
            label_y = graph_height + 10 + (row * 10)
            
            anchor = "center" 
            if px < 20: anchor = "w"
            elif px > width - 20: anchor = "e"
            
            label_text = f"{s:.{peak_decimals}f}"
            canvas.create_text(px, label_y, text=label_text, fill="#FFFF00", font=peak_font, anchor=anchor)


    def draw_graph(self):
        if not self.show_graph.get(): return
        
        if self.graph_show_mag.get():
            self.draw_single_graph(self.canvas_mag, 1, "#00FF00", "MAGNITUDE")
        if self.graph_show_x.get():
            self.draw_single_graph(self.canvas_x, 2, "#FF5555", "X VELOCITY")
        if self.graph_show_y.get():
            self.draw_single_graph(self.canvas_y, 3, "#55FF55", "Y VELOCITY")
        if self.graph_show_z.get():
            self.draw_single_graph(self.canvas_z, 4, "#5555FF", "Z VELOCITY")

    def polling_loop(self):
        while self.running:
            try:
                # Sleep based on rate
                rate_sec = self.thread_poll_rate / 1000.0
                if rate_sec < 0.001: rate_sec = 0.001
                time.sleep(rate_sec)
                
                current_time = time.time()
                
                if not self.attached:
                    if self.mem.attach(PROCESS_NAME):
                        self.attached = True
                        self.status_msg = "Attached. resolving pointer..."
                    else:
                        self.status_msg = "Game not found..."
                
                if self.attached:
                    mod_base, mod_size = self.mem.get_module(BASE_MODULE)
                    if mod_base:
                        if VELOCITY_SIGNATURE:
                            # Try Signature Scan
                            scan_res = self.mem.scan_pattern(BASE_MODULE, VELOCITY_SIGNATURE)
                            if scan_res:
                                self.player_address = self.mem.resolve_chain(scan_res + VELOCITY_SIG_OFFSET, POINTER_OFFSETS)
                                if self.player_address:
                                    self.status_msg = f"Linked (AOB): {hex(self.player_address).upper()}"
                                else:
                                    self.status_msg = "AOB Found, resolving chain..."
                            else:
                                # Fallback to static
                                self.player_address = self.mem.resolve_chain(mod_base + BASE_OFFSET, POINTER_OFFSETS)
                                if self.player_address:
                                    self.status_msg = f"Linked (Static): {hex(self.player_address).upper()}"
                                else:
                                    self.status_msg = "Scanning AOB..."
                        else:
                            # Use Static Pointer
                            self.player_address = self.mem.resolve_chain(mod_base + BASE_OFFSET, POINTER_OFFSETS)
                            if self.player_address:
                                self.status_msg = f"Linked: {hex(self.player_address).upper()}"
                            else:
                                self.status_msg = "Resolving chain..."
                    else:
                        self.status_msg = f"Waiting for {BASE_MODULE}..."

                    if self.player_address:
                        vx = self.mem.read_float(self.player_address + OFFSET_VELOCITY)
                        vy = self.mem.read_float(self.player_address + OFFSET_GRAVITY) 
                        vz = self.mem.read_float(self.player_address + OFFSET_VELOCITY + 8)
                        
                        speed = math.sqrt(vx*vx + vy*vy + vz*vz)
                        
                        if speed < 100000:
                            self.data_queue.put((current_time, speed, vx, vy, vz))
                        else:
                            self.player_address = 0
            except Exception as e:
                self.attached = False
                self.status_msg = "Error reading memory"
                time.sleep(1)

    def update_ui(self):
        # Consume queue
        while not self.data_queue.empty():
            try:
                item = self.data_queue.get_nowait()
                self.history.append(item)
                
                if self.data_queue.empty():
                    current_time, speed, vx, vy, vz = item
                    
                    prec_mag = self.precision_mag.get()
                    prec_vec = self.precision_vec.get()
                    
                    self.label_speed.config(text=f"{speed:.{prec_mag}f} m/s")
                    self.label_vx.config(text=f"X: {vx:.{prec_vec}f}")
                    self.label_vy.config(text=f"Y: {vy:.{prec_vec}f}")
                    self.label_vz.config(text=f"Z: {vz:.{prec_vec}f}")
            except queue.Empty:
                break
        
        self.label_status.config(text=self.status_msg)
        
        if "Linked" not in self.status_msg:
             self.label_speed.config(text="--")
             self.label_vx.config(text="X: --")
             self.label_vy.config(text="Y: --")
             self.label_vz.config(text="Z: --")
        
        current_time = time.time()
        while self.history and (current_time - self.history[0][0] > self.history_duration):
            self.history.popleft()
            
        self.draw_graph()
        self.root.after(33, self.update_ui)

if __name__ == "__main__":
    try:
        root = tk.Tk()
        app = VelocityOverlay(root)
        root.mainloop()
    except Exception as e:
        import traceback
        with open("crash_log.txt", "w") as f:
            traceback.print_exc(file=f)
            f.write(f"\nError: {e}")
