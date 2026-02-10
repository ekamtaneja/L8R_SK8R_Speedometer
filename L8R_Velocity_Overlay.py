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
#  L8R SK8R VELOCITY OVERLAY (Python Edition)
# ==============================================================================
#
#  INSTRUCTIONS:
#  1. Find the Pointer Chain using Cheat Engine (as explained in the chat).
#  2. Enter the values in the 'Configuration' section below.
#  3. Run this script.
#
# ==============================================================================

# --- Configuration ------------------------------------------------------------

PROCESS_NAME = "l8rsk8r.exe"

# POINTER CHAIN CONFIGURATION
# Based on your Screenshot:
# "mono-2.0-bdwgc.dll" + 00A044C0 -> 7DC -> 48 -> 288 -> 0 -> 0
BASE_MODULE = "mono-2.0-bdwgc.dll" 

# BASE_OFFSET: The number added to the module address (e.g., 0x01234567)
BASE_OFFSET = 0x00A044C0  

# POINTER_OFFSETS: The list of offsets to follow. 
# IMPORTANT: Use '0x' prefix for Hexadecimal numbers from Cheat Engine!
# REMOVED last 0x0 because it likely points to the VTable (Class Info) instead of the Player object.
POINTER_OFFSETS = [0x7DC, 0x48, 0x288, 0x0] 

# VELOCITY OFFSET (Final offset to the velocity struct/fields)
OFFSET_VELOCITY = 0x24C
OFFSET_GRAVITY = 0x27C

# DIRECT ADDRESS OVERRIDE (Optional)
# If you don't have a chain yet, paste the 'Instance' address from Cheat Engine here.
# Set to None to use the Pointer Chain.
OVERRIDE_ADDRESS = None
# Example: OVERRIDE_ADDRESS = 0x1234ABCD00

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
        # 1. Read the pointer at the Base Address
        current_addr = self.read_ptr(base_addr)
        print(f"Base: {hex(base_addr)} -> {hex(current_addr)}")
        if not current_addr: return 0
        
        # 2. Iterate through offsets
        for i, offset in enumerate(offsets):
            prev_addr = current_addr
            # For the pointer chain provided, we read the pointer at (current + offset)
            current_addr = self.read_ptr(current_addr + offset)
            print(f"Offset[{i}] {hex(offset)}: {hex(prev_addr)}+{hex(offset)} -> {hex(current_addr)}")
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
        # Increased height for graph
        self.root.geometry("250x200+50+50")
        self.root.configure(bg='black')

        # --- Settings ---
        self.show_magnitude = tk.BooleanVar(value=True)
        self.show_vectors = tk.BooleanVar(value=True)
        self.show_graph = tk.BooleanVar(value=True)
        
        # Call refresh_layout when variables change
        self.show_magnitude.trace_add("write", lambda *args: self.refresh_layout())
        self.show_vectors.trace_add("write", lambda *args: self.refresh_layout())
        self.show_graph.trace_add("write", lambda *args: self.refresh_layout())

        # --- Data ---
        self.history = deque()
        self.history_duration = 30.0 # seconds

        # --- UI Components ---
        
        # 1. Magnitude
        self.label_speed = tk.Label(root, text="WAITING...", font=("Consolas", 24, "bold"), fg="#00FF00", bg="black")
        
        # 2. Vector components
        self.frame_vec = tk.Frame(root, bg="black")
        self.label_vx = tk.Label(self.frame_vec, text="X: 0.00", font=("Consolas", 10), fg="#FF5555", bg="black")
        self.label_vx.pack(side="left", expand=True)
        self.label_vy = tk.Label(self.frame_vec, text="Y: 0.00", font=("Consolas", 10), fg="#55FF55", bg="black")
        self.label_vy.pack(side="left", expand=True)
        self.label_vz = tk.Label(self.frame_vec, text="Z: 0.00", font=("Consolas", 10), fg="#5555FF", bg="black")
        self.label_vz.pack(side="left", expand=True)
        
        # 3. Graph
        self.canvas = tk.Canvas(root, bg="black", height=60, highlightthickness=0)

        # 4. Status
        self.label_status = tk.Label(root, text="Searching for game...", font=("Arial", 8), fg="white", bg="black")

        # Initial layout
        self.refresh_layout()

        # Context Menu
        self.menu = tk.Menu(root, tearoff=0)
        self.menu.add_checkbutton(label="Show Magnitude", variable=self.show_magnitude)
        self.menu.add_checkbutton(label="Show Vectors", variable=self.show_vectors)
        self.menu.add_checkbutton(label="Show Graph", variable=self.show_graph)
        self.menu.add_separator()
        self.menu.add_command(label="Exit", command=sys.exit)

        # Bindings
        self.root.bind("<ButtonPress-1>", self.start_move)
        self.root.bind("<B1-Motion>", self.do_move)
        self.root.bind("<Button-3>", self.show_context_menu) # Right click
        self.root.bind("<Double-Button-1>", lambda e: sys.exit())

        self.mem = MemoryReader()
        self.attached = False
        self.player_address = 0
        
        self.update()

    def show_context_menu(self, event):
        self.menu.post(event.x_root, event.y_root)

    def refresh_layout(self):
        # Clear all
        self.label_speed.pack_forget()
        self.frame_vec.pack_forget()
        self.canvas.pack_forget()
        self.label_status.pack_forget()

        # Repack based on settings
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
        if width <= 1: width = 240 # fallback

        # Find time window
        now = self.history[-1][0]
        start_time = now - self.history_duration
        
        # Find scale
        max_speed = 0.0
        for t, s in self.history:
            if s > max_speed: max_speed = s
        
        if max_speed < 10.0: max_speed = 10.0 # Min vertical scale
        
        # Draw lines
        points = []
        for t, s in self.history:
            if t < start_time: continue
            
            # Normalize X: 0 to width
            # t goes from start_time to now
            x = (t - start_time) / self.history_duration * width
            
            # Normalize Y: height to 0 (0 is top)
            y = height - (s / max_speed * height)
            
            points.append(x)
            points.append(y)
            
        if len(points) >= 4:
            self.canvas.create_line(points, fill="#00FF00", width=2)
            
        # Draw max speed indicator
        self.canvas.create_text(2, 2, anchor="nw", text=f"{max_speed:.1f}", fill="#555555", font=("Arial", 8))

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
                if OVERRIDE_ADDRESS:
                    # Direct address mode
                    self.player_address = OVERRIDE_ADDRESS
                    self.label_status.config(text=f"Direct: {hex(self.player_address).upper()}")
                else:
                    # Pointer Chain mode
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
                    # Use gravity/vertical speed field for Y since the vector Y is unused
                    vy = self.mem.read_float(self.player_address + OFFSET_GRAVITY) 
                    vz = self.mem.read_float(self.player_address + OFFSET_VELOCITY + 8)
                    
                    speed = math.sqrt(vx*vx + vy*vy + vz*vz)
                    
                    if speed < 100000: # Filter garbage
                        self.label_speed.config(text=f"{speed:.2f} m/s")
                        self.label_vx.config(text=f"X: {vx:.2f}")
                        self.label_vy.config(text=f"Y: {vy:.2f}")
                        self.label_vz.config(text=f"Z: {vz:.2f}")
                        
                        # Graph history update
                        self.history.append((current_time, speed))
                        
                    else:
                        self.label_speed.config(text="GARBAGE")
                        self.label_vx.config(text="X: --")
                        self.label_vy.config(text="Y: --")
                        self.label_vz.config(text="Z: --")
                        self.player_address = 0 # Reset if pointer is bad
        except Exception as e:
            print(e)
            self.attached = False
            self.label_status.config(text="Error reading memory")

        # Prune history
        while self.history and (current_time - self.history[0][0] > self.history_duration):
            self.history.popleft()
            
        self.draw_graph()

        self.root.after(50, self.update)

if __name__ == "__main__":
    root = tk.Tk()
    app = VelocityOverlay(root)
    root.mainloop()
