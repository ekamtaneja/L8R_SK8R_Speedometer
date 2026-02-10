import ctypes
import tkinter as tk
from tkinter import ttk
from ctypes import wintypes
import sys
import math
import time
import struct
from collections import deque

# ==============================================================================
#  L8R SK8R VELOCITY OVERLAY
# ==============================================================================

# --- Configuration ------------------------------------------------------------

PROCESS_NAME = "l8rsk8r.exe"
BASE_MODULE = "mono-2.0-bdwgc.dll" 
BASE_OFFSET = 0x00A044C0  
POINTER_OFFSETS = [0x7DC, 0x48, 0x288, 0x0] 
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
        if snapshot == -1 or snapshot == 0: return None
    except:
        return None

    base_addr = None
    entry = MODULEENTRY32()
    entry.dwSize = ctypes.sizeof(MODULEENTRY32)
    
    if kernel32.Module32First(snapshot, ctypes.byref(entry)):
        while True:
            try:
                m_name = entry.szModule.decode('utf-8').lower()
                if module_name.lower() == m_name:
                    base_addr = entry.modBaseAddr
                    break
            except:
                pass
            if not kernel32.Module32Next(snapshot, ctypes.byref(entry)):
                break
    kernel32.CloseHandle(snapshot)
    return base_addr

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
        if not self.pid: return 0
        return get_module_base(self.pid, module_name) or 0

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
        self.root.geometry("250x200+50+50")
        self.root.configure(bg='black')

        # --- Settings ---
        self.show_magnitude = tk.BooleanVar(value=True)
        self.show_vectors = tk.BooleanVar(value=True)
        self.show_graph = tk.BooleanVar(value=True)

        self.graph_show_mag = tk.BooleanVar(value=True)
        self.graph_show_x = tk.BooleanVar(value=False)
        self.graph_show_y = tk.BooleanVar(value=False)
        self.graph_show_z = tk.BooleanVar(value=False)
        
        self.font_size_mag = tk.IntVar(value=24)
        self.font_size_vec = tk.IntVar(value=10)
        self.font_size_peak = tk.IntVar(value=8)
        
        self.peak_update_rate = tk.DoubleVar(value=2.0)

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
            
            self.graph_show_mag.trace_add("write", lambda *args: self.draw_graph())
            self.graph_show_x.trace_add("write", lambda *args: self.draw_graph())
            self.graph_show_y.trace_add("write", lambda *args: self.draw_graph())
            self.graph_show_z.trace_add("write", lambda *args: self.draw_graph())
        except AttributeError:
            self.show_magnitude.trace("w", lambda *args: self.refresh_layout())
            self.show_vectors.trace("w", lambda *args: self.refresh_layout())
            self.show_graph.trace("w", lambda *args: self.refresh_layout())
            # For older python versions, skipping detailed traces or using simpler approach if needed
            self.font_size_mag.trace("w", update_fonts)
            self.font_size_vec.trace("w", update_fonts)

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
        
        self.canvas = tk.Canvas(root, bg="black", height=100, highlightthickness=0)
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

        self.mem = MemoryReader()
        self.attached = False
        self.player_address = 0
        
        self.update()

    def show_context_menu(self, event):
        self.menu.post(event.x_root, event.y_root)
        
    def open_settings(self):
        settings_win = tk.Toplevel(self.root)
        settings_win.title("Settings")
        settings_win.geometry("300x450")
        settings_win.configure(bg="#222222")
        settings_win.attributes('-topmost', True)
        
        style = ttk.Style()
        style.theme_use('clam')
        
        def create_scale(parent, label, var, from_, to_):
            frame = tk.Frame(parent, bg="#222222")
            frame.pack(fill="x", padx=10, pady=5)
            tk.Label(frame, text=label, fg="white", bg="#222222").pack(anchor="w")
            scale = tk.Scale(frame, from_=from_, to=to_, orient="horizontal", variable=var, 
                             bg="#222222", fg="white", highlightthickness=0)
            scale.pack(fill="x")
            
        def create_check(parent, label, var):
            cb = tk.Checkbutton(parent, text=label, variable=var, bg="#222222", fg="white", 
                                selectcolor="#444444", activebackground="#222222", activeforeground="white")
            cb.pack(anchor="w", padx=10)

        # Font Settings
        lbl_fonts = tk.Label(settings_win, text="Font Sizes", fg="#AAAAAA", bg="#222222", font=("Arial", 10, "bold"))
        lbl_fonts.pack(anchor="w", padx=5, pady=(10, 0))
        create_scale(settings_win, "Magnitude Font", self.font_size_mag, 10, 72)
        create_scale(settings_win, "Vectors Font", self.font_size_vec, 8, 32)
        create_scale(settings_win, "Graph Peak Font", self.font_size_peak, 6, 20)
        
        # Update Rate
        lbl_rate = tk.Label(settings_win, text="Update Rate", fg="#AAAAAA", bg="#222222", font=("Arial", 10, "bold"))
        lbl_rate.pack(anchor="w", padx=5, pady=(10, 0))
        create_scale(settings_win, "Top Speed Update (sec)", self.peak_update_rate, 0.1, 10.0)
        
        # Graph Visibility
        lbl_graph = tk.Label(settings_win, text="Graph Lines", fg="#AAAAAA", bg="#222222", font=("Arial", 10, "bold"))
        lbl_graph.pack(anchor="w", padx=5, pady=(10, 0))
        create_check(settings_win, "Show Magnitude (Green)", self.graph_show_mag)
        create_check(settings_win, "Show X (Red)", self.graph_show_x)
        create_check(settings_win, "Show Y (Light Green)", self.graph_show_y)
        create_check(settings_win, "Show Z (Blue)", self.graph_show_z)


    def refresh_layout(self):
        self.label_speed.pack_forget()
        self.frame_vec.pack_forget()
        self.canvas.pack_forget()
        self.label_status.pack_forget()

        if self.show_magnitude.get():
            self.label_speed.pack(pady=(10, 0))
        
        if self.show_vectors.get():
            self.frame_vec.pack(fill="x", pady=5)
            
        if self.show_graph.get():
            self.canvas.pack(fill="x", pady=5, padx=5)
            
        self.label_status.pack(side="bottom")

    def start_move(self, event):
        self.root.x = event.x
        self.root.y = event.y

    def do_move(self, event):
        x = self.root.winfo_x() + (event.x - self.root.x)
        y = self.root.winfo_y() + (event.y - self.root.y)
        self.root.geometry(f"+{x}+{y}")

    def draw_graph(self):
        if not self.show_graph.get(): return
        
        self.canvas.delete("all")
        
        if len(self.history) < 2: return

        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        if width <= 1: width = 240
        
        margin_bottom = 20
        graph_height = height - margin_bottom

        # Create local copy for analysis
        data = list(self.history)
        now = data[-1][0]
        start_time = now - self.history_duration
        
        # Determine which graphs to draw
        draw_mag = self.graph_show_mag.get()
        draw_x = self.graph_show_x.get()
        draw_y = self.graph_show_y.get()
        draw_z = self.graph_show_z.get()
        
        # Collect values to determine scale
        all_values = []
        if draw_mag: all_values.extend([d[1] for d in data])
        if draw_x: all_values.extend([d[2] for d in data])
        if draw_y: all_values.extend([d[3] for d in data])
        if draw_z: all_values.extend([d[4] for d in data])
        
        if not all_values: return # Nothing to draw

        max_val = max(all_values)
        min_val = min(all_values)
        
        # Adjust scale to always include 0
        if min_val > 0: min_val = 0
        if max_val < 0: max_val = 0
        
        val_range = max_val - min_val
        if val_range < 10.0: val_range = 10.0 # Minimum range
        
        # 2. Draw Grid
        # Zero line
        zero_y = graph_height - ((0 - min_val) / val_range * graph_height)
        self.canvas.create_line(0, zero_y, width, zero_y, fill="#555555")
        
        # Grid lines
        grid_interval = 10.0
        # Positive grid
        curr = 0
        while curr < max_val:
            y = graph_height - ((curr - min_val) / val_range * graph_height)
            if y >= 0 and y <= graph_height:
                self.canvas.create_line(0, y, width, y, fill="#333333", dash=(4, 4))
            curr += grid_interval
            
        # Negative grid
        curr = -10.0
        while curr > min_val:
            y = graph_height - ((curr - min_val) / val_range * graph_height)
            if y >= 0 and y <= graph_height:
                self.canvas.create_line(0, y, width, y, fill="#333333", dash=(4, 4))
            curr -= grid_interval
            
        self.canvas.create_text(2, 2, anchor="nw", text=f"{max_val:.1f}", fill="#555555", font=("Arial", 8))
        self.canvas.create_text(2, graph_height - 10, anchor="sw", text=f"{min_val:.1f}", fill="#555555", font=("Arial", 8))

        # Helper to draw line
        def plot_line(index, color):
            points = []
            for item in data:
                t = item[0]
                val = item[index]
                if t < start_time: continue
                x = (t - start_time) / self.history_duration * width
                y = graph_height - ((val - min_val) / val_range * graph_height)
                points.append(x)
                points.append(y)
            if len(points) >= 4:
                self.canvas.create_line(points, fill=color, width=2)

        if draw_x: plot_line(2, "#FF5555")
        if draw_y: plot_line(3, "#55FF55")
        if draw_z: plot_line(4, "#5555FF")
        if draw_mag: plot_line(1, "#00FF00")

        # 4. Find Peaks (Local Maxima) for Magnitude only if enabled, or just update peaks based on magnitude?
        # User asked for "font size of the top speed in the graph", usually implying Magnitude.
        # But if Mag is off, maybe show peaks for highest visible?
        # Let's stick to Magnitude for peaks as that's "Top Speed".
        
        if draw_mag:
            peaks = []
            for i in range(1, len(data) - 1):
                t = data[i][0]
                s = data[i][1] # Magnitude
                prev_s = data[i-1][1]
                next_s = data[i+1][1]
                
                if s > prev_s and s > next_s and s > 1.0: 
                    peaks.append((t, s))
            
            peaks.sort(key=lambda x: x[1], reverse=True)
            
            selected_peaks = []
            update_rate = self.peak_update_rate.get()
            
            for p in peaks:
                t, s = p
                conflict = False
                for sp in selected_peaks:
                    if abs(t - sp[0]) < update_rate: 
                        conflict = True
                        break
                if not conflict:
                    selected_peaks.append(p)
            
            peak_font = ("Arial", self.font_size_peak.get(), "bold")
            
            for t, s in selected_peaks:
                if t < start_time: continue
                
                px = (t - start_time) / self.history_duration * width
                py = graph_height - ((s - min_val) / val_range * graph_height)
                
                self.canvas.create_line(px, py, px, graph_height, fill="#FFFF00", dash=(2, 4))
                
                label_y = graph_height + 10 
                anchor = "center" 
                if px < 20: anchor = "w"
                elif px > width - 20: anchor = "e"
                
                self.canvas.create_text(px, label_y, text=f"{s:.1f}", fill="#FFFF00", font=peak_font, anchor=anchor)

    def update(self):
        try:
            current_time = time.time()
            
            if not self.attached:
                if self.mem.attach(PROCESS_NAME):
                    self.attached = True
                    self.label_status.config(text="Attached. resolving pointer...")
                else:
                    self.label_status.config(text="Game not found...")
            
            if self.attached:
                mod_base = self.mem.get_module(BASE_MODULE)
                if mod_base:
                    self.player_address = self.mem.resolve_chain(mod_base + BASE_OFFSET, POINTER_OFFSETS)
                    if self.player_address:
                        self.label_status.config(text=f"Linked: {hex(self.player_address).upper()}")
                    else:
                        self.label_status.config(text="Resolving chain...")
                else:
                    self.label_status.config(text=f"Waiting for {BASE_MODULE}...")

                if self.player_address:
                    vx = self.mem.read_float(self.player_address + OFFSET_VELOCITY)
                    vy = self.mem.read_float(self.player_address + OFFSET_GRAVITY) 
                    vz = self.mem.read_float(self.player_address + OFFSET_VELOCITY + 8)
                    
                    speed = math.sqrt(vx*vx + vy*vy + vz*vz)
                    
                    if speed < 100000:
                        self.label_speed.config(text=f"{speed:.2f} m/s")
                        self.label_vx.config(text=f"X: {vx:.2f}")
                        self.label_vy.config(text=f"Y: {vy:.2f}")
                        self.label_vz.config(text=f"Z: {vz:.2f}")
                        # Store all components: time, speed, vx, vy, vz
                        self.history.append((current_time, speed, vx, vy, vz))
                    else:
                        self.label_speed.config(text="GARBAGE")
                        self.label_vx.config(text="X: --")
                        self.label_vy.config(text="Y: --")
                        self.label_vz.config(text="Z: --")
                        self.player_address = 0
        except Exception as e:
            self.attached = False
            self.label_status.config(text="Error reading memory")

        while self.history and (current_time - self.history[0][0] > self.history_duration):
            self.history.popleft()
            
        self.draw_graph()
        self.root.after(50, self.update)

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
