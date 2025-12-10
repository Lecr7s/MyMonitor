import cv2
import tkinter as tk
from tkinter import messagebox, ttk
import customtkinter as ctk
from PIL import Image, ImageTk, ImageDraw
from threading import Thread, Lock
import time
import datetime
import os
import sys
import winsound
import json
import logging
from typing import Optional, Tuple, Dict, Any
import pystray
from pystray import MenuItem as item

# 设置CustomTkinter外观
ctk.set_appearance_mode("dark")  # 深色主题
ctk.set_default_color_theme("blue")  # 蓝色主题

# --- 1. 环境与配置 (完全保留你的严谨逻辑) ---
def get_base_path():
    """获取脚本或打包后exe的根目录"""
    # PyInstaller creates a temp folder and stores path in _MEIPASS
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

SCRIPT_DIR = get_base_path()
LOG_FILE = os.path.join(SCRIPT_DIR, 'security_monitor.log')
CONFIG_FILE = os.path.join(SCRIPT_DIR, 'config.json')
SCREENSHOT_DIR = os.path.join(SCRIPT_DIR, 'screenshots')

# 确保截图目录存在
if not os.path.exists(SCREENSHOT_DIR):
    os.makedirs(SCREENSHOT_DIR)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler(LOG_FILE, encoding='utf-8'), logging.StreamHandler()]
)

# 默认配置 (严格对应你脚本中的参数)
DEFAULT_CONFIG = {
    "camera_id": 0,
    "min_area": 500,
    "alert_cooldown": 3,
    "loop_delay": 0.2,
    "roi": None,
    "threshold": 25,
    "gaussian_blur": 21,
    "dilate_iterations": 2,
    "max_failures": 10,
    "show_preview": True,
    "auto_screenshot": True,
    "manual_screenshot": True,
    "continuous_frames": 3,      # 核心防抖参数
    "screenshot_count": 3,       # 报警连拍张数
    "screenshot_interval": 0.5,  # 连拍间隔
    "auto_cleanup_enabled": True,  # 自动清理旧截图
    "cleanup_days": 3,           # 保留截图天数
    "memory_cleanup_interval": 3600,  # 内存清理间隔（秒）
    "custom_presets": {}  # 用户自定义预设
}

# === 统一的UI配色方案 ===
COLOR_BUTTON_BG = "#00B0F0"     # 按钮背景-亮蓝色 rgb(0,176,240)
COLOR_TEXT_BLUE = "#00B0F0"     # 蓝色文字 rgb(0,176,240)
COLOR_PRIMARY = "#1E386B"       # 保留兼容
COLOR_PRIMARY_LIGHT = "#64B5F6" # 浅蓝色
COLOR_PRIMARY_DARK = "#1E386B"  # 深蓝色（按钮hover时不变色）
COLOR_SUCCESS = "#4CAF50"       # 成功/正常-绿色
COLOR_WARNING = "#FF9800"       # 警告-橙色
COLOR_DANGER = "#FF5722"        # 危险/报警-红色
COLOR_TEXT_PRIMARY = "#FFFFFF"  # 主文本-白色
COLOR_TEXT_SECONDARY = "#B0BEC5" # 次要文本-灰色
COLOR_BG_DARK = "#1a1a1a"      # 深色背景
COLOR_BG_MEDIUM = "#2b2b2b"    # 中度背景
COLOR_BG_LIGHT = "#3a3a3a"     # 浅色背景

# === 统一的字体方案 ===
FONT_FAMILY = "Microsoft YaHei"  # 中文字体
FONT_MONO = "Consolas"          # 等宽字体
FONT_SIZE_TITLE = 15            # 标题字号（增大）
FONT_SIZE_LARGE = 13            # 大字号（增大）
FONT_SIZE_NORMAL = 12           # 正常字号（增大）
FONT_SIZE_SMALL = 10            # 小字号

def validate_roi(roi: Tuple[int, int, int, int], frame_shape: Tuple[int, int, int]) -> bool:
    """ROI边界验证逻辑"""
    x, y, w, h = roi
    frame_h, frame_w = frame_shape[:2]
    if x < 0 or y < 0 or w <= 0 or h <= 0: return False
    if x + w > frame_w or y + h > frame_h: return False
    return True

# ==================== 辅助工具类 ====================

class ToolTip:
    """工具提示类 - 鼠标悬停显示提示信息"""
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tooltip_window = None
        self.widget.bind("<Enter>", self.show_tooltip)
        self.widget.bind("<Leave>", self.hide_tooltip)

    def show_tooltip(self, event=None):
        if self.tooltip_window or not self.text:
            return

        # 计算提示框位置
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5

        # 创建顶层窗口
        self.tooltip_window = tk.Toplevel(self.widget)
        self.tooltip_window.wm_overrideredirect(True)
        self.tooltip_window.wm_geometry(f"+{x}+{y}")

        # 创建标签显示文本
        label = tk.Label(self.tooltip_window, text=self.text,
                        background=COLOR_BG_MEDIUM, foreground="white",
                        relief="solid", borderwidth=1,
                        font=(FONT_FAMILY, FONT_SIZE_NORMAL, "bold"),
                        padx=8, pady=4)
        label.pack()

    def hide_tooltip(self, event=None):
        if self.tooltip_window:
            self.tooltip_window.destroy()
            self.tooltip_window = None


class CollapsibleFrame(ctk.CTkFrame):
    """可折叠面板 - 带展开/收起按钮的框架"""
    def __init__(self, parent, title, **kwargs):
        super().__init__(parent, corner_radius=8, **kwargs)

        self.is_collapsed = False

        # 标题栏（可点击）
        self.title_frame = ctk.CTkFrame(self, fg_color="transparent", cursor="hand2")
        self.title_frame.pack(fill="x", padx=5, pady=5)

        # 展开/折叠图标
        self.toggle_icon = ctk.CTkLabel(self.title_frame, text="▼",
                                       font=("Arial", 12),
                                       text_color=COLOR_TEXT_BLUE,
                                       width=20)
        self.toggle_icon.pack(side="left", padx=(5, 0))

        # 标题文本
        self.title_label = ctk.CTkLabel(self.title_frame, text=title,
                                       font=(FONT_FAMILY, FONT_SIZE_TITLE, "bold"),
                                       text_color=COLOR_TEXT_BLUE)
        self.title_label.pack(side="left", padx=5)

        # 内容容器
        self.content_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.content_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # 绑定点击事件
        self.title_frame.bind("<Button-1>", lambda e: self.toggle())
        self.toggle_icon.bind("<Button-1>", lambda e: self.toggle())
        self.title_label.bind("<Button-1>", lambda e: self.toggle())

    def toggle(self):
        """切换折叠状态"""
        self.is_collapsed = not self.is_collapsed

        if self.is_collapsed:
            self.content_frame.pack_forget()
            self.toggle_icon.configure(text="▶")
        else:
            self.content_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
            self.toggle_icon.configure(text="▼")

    def get_content_frame(self):
        """获取内容框架，用于添加子控件"""
        return self.content_frame


class SecurityApp:
    def __init__(self, root):
        self.root = root
        self.root.title("实验室智能监控系统 v3.0 Pro")

        # 加载窗口布局（如果有保存的配置则使用，否则使用默认值）
        self.load_window_layout()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # 设置窗口最小大小
        self.root.minsize(1200, 700)

        # --- 状态变量初始化 ---
        self.config = self.load_config()
        self.lock = Lock()
        self.cap = None
        self.is_running = False
        self.is_paused = False
        self.is_alerting = False
        
        self.last_alert_time = 0
        self.alert_count = 0
        self.screenshot_count = 0
        self.motion_frame_count = 0 # 连续检测计数器

        # FPS计算相关
        self.fps = 0.0
        self.frame_count = 0
        self.fps_start_time = time.time()

        # 运行时长
        self.start_time = None

        # ROI重置标志
        self.roi_reset_flag = False
        self.roi_selecting = False  # ROI选择中标志，防止重复调用

        # 报警历史记录
        self.alert_history = []  # 存储报警记录：{'time': str, 'frames': int, 'screenshots': [str]}

        # 音效配置
        self.sound_enabled = tk.BooleanVar(value=True)
        self.sound_type = tk.StringVar(value="标准警报")

        # 系统托盘相关
        self.tray_icon = None
        self.tray_running = False

        # 窗口可见性标志（用于性能优化）
        self.window_visible = True

        # --- 构建界面 ---
        self.setup_ui()

        # 应用保存的窗口布局（分隔条位置等）
        self.apply_saved_layout()

        # 如果已有ROI配置，自动调整灵敏度范围
        if self.config.get('roi') and len(self.config['roi']) == 4:
            self.update_sensitivity_range(self.config['roi'])

        # 性能优化相关
        self.last_memory_cleanup = time.time()
        self.last_screenshot_cleanup = time.time()

        # 启动时清理旧截图
        if self.config.get('auto_cleanup_enabled', True):
            Thread(target=self.cleanup_old_screenshots, daemon=True).start()

        self.log(f"系统就绪。灵敏度阈值: {self.config['min_area']}, 防抖帧数: {self.config['continuous_frames']}")
        self.log("快捷键: Space(启动/暂停) | Ctrl+S(截图) | Ctrl+R(重设ROI) | Ctrl+1/2/3(预设)")

        # 初始化系统托盘
        self.init_tray()

        # 加载自定义预设
        self._populate_presets_combo()

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding='utf-8') as f:
                    user_config = json.load(f)
                    # 更新默认配置，确保新参数存在
                    config = DEFAULT_CONFIG.copy()
                    config.update(user_config)
                    return config
            except: pass
        return DEFAULT_CONFIG.copy()

    def save_config(self):
        try:
            with open(CONFIG_FILE, "w", encoding='utf-8') as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            self.log(f"配置保存失败: {e}")

    def load_window_layout(self):
        """加载窗口布局配置"""
        layout_file = os.path.join(os.path.dirname(CONFIG_FILE), "window_layout.json")
        default_geometry = "1400x850+100+50"  # 默认大小和位置

        self.saved_layout = None  # 保存布局数据供后续使用

        if os.path.exists(layout_file):
            try:
                with open(layout_file, "r", encoding='utf-8') as f:
                    layout = json.load(f)
                    self.saved_layout = layout  # 保存布局数据
                    geometry = layout.get("geometry", default_geometry)
                    self.root.geometry(geometry)
                    logging.info(f"窗口布局已加载: {geometry}")
                    return
            except Exception as e:
                logging.warning(f"加载窗口布局失败: {e}")

        # 使用默认配置
        self.root.geometry(default_geometry)

    def save_window_layout(self):
        """保存当前窗口布局"""
        try:
            layout_file = os.path.join(os.path.dirname(CONFIG_FILE), "window_layout.json")
            # 获取当前窗口几何信息
            geometry = self.root.geometry()

            # 获取PanedWindow分隔条位置
            sash_position = None
            if hasattr(self, 'paned_window'):
                try:
                    sash_position = self.paned_window.sashpos(0)
                except:
                    pass

            layout = {
                "geometry": geometry,
                "sash_position": sash_position,
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

            with open(layout_file, "w", encoding='utf-8') as f:
                json.dump(layout, f, indent=4, ensure_ascii=False)

            logging.info(f"窗口布局已保存: {geometry}, 分隔条: {sash_position}")
        except Exception as e:
            logging.error(f"保存窗口布局失败: {e}")

    def apply_saved_layout(self):
        """应用保存的窗口布局（分隔条位置等）"""
        if not self.saved_layout:
            return

        try:
            # 应用PanedWindow分隔条位置
            sash_position = self.saved_layout.get("sash_position")
            if sash_position and hasattr(self, 'paned_window'):
                # 使用after延迟应用，确保窗口已完全渲染
                self.root.after(100, lambda: self.paned_window.sashpos(0, sash_position))
                logging.info(f"分隔条位置已应用: {sash_position}")
        except Exception as e:
            logging.warning(f"应用窗口布局失败: {e}")

    def setup_ui(self):
        # 1. 顶部控制栏
        ctrl_frame = ctk.CTkFrame(self.root, corner_radius=10)
        ctrl_frame.pack(fill="x", padx=15, pady=10)

        # 控制标题
        ctk.CTkLabel(ctrl_frame, text="● 控制中心", font=(FONT_FAMILY, FONT_SIZE_TITLE, "bold"),
                    text_color=COLOR_TEXT_BLUE).pack(side="left", padx=15, pady=10)

        # 主控按钮 - 使用深蓝色背景，白色文字，点击不变色
        self.btn_start = ctk.CTkButton(ctrl_frame, text="▶ 启动监控",
                                      font=(FONT_FAMILY, FONT_SIZE_LARGE, "bold"),
                                      fg_color=COLOR_BUTTON_BG, hover_color=COLOR_BUTTON_BG,
                                      text_color=COLOR_TEXT_PRIMARY,
                                      text_color_disabled="#E0E0E0",
                                      width=120, height=35,
                                      command=self.start_monitoring)
        self.btn_start.pack(side="left", padx=5, pady=10)
        ToolTip(self.btn_start, "开始视频监控\n快捷键: Space")

        self.btn_pause = ctk.CTkButton(ctrl_frame, text="⏸ 暂停",
                                      font=(FONT_FAMILY, FONT_SIZE_LARGE, "bold"),
                                      fg_color=COLOR_BUTTON_BG, hover_color=COLOR_BUTTON_BG,
                                      text_color=COLOR_TEXT_PRIMARY,
                                      text_color_disabled="#E0E0E0",
                                      width=100, height=35,
                                      command=self.toggle_pause, state="disabled")
        self.btn_pause.pack(side="left", padx=5, pady=10)
        ToolTip(self.btn_pause, "暂停/恢复监控\n暂停时不会触发报警")

        self.btn_stop = ctk.CTkButton(ctrl_frame, text="⏹ 停止",
                                     font=(FONT_FAMILY, FONT_SIZE_LARGE, "bold"),
                                     fg_color=COLOR_BUTTON_BG, hover_color=COLOR_BUTTON_BG,
                                     text_color=COLOR_TEXT_PRIMARY,
                                     text_color_disabled="#E0E0E0",
                                     width=100, height=35,
                                     command=self.stop_monitoring, state="disabled")
        self.btn_stop.pack(side="left", padx=5, pady=10)
        ToolTip(self.btn_stop, "停止监控并释放摄像头")

        # 分隔符（使用Frame模拟）
        ctk.CTkFrame(ctrl_frame, width=2, height=35, fg_color=COLOR_BG_LIGHT).pack(side="left", padx=10, pady=10)

        # 辅助按钮
        self.btn_roi = ctk.CTkButton(ctrl_frame, text="◪ 重设区域",
                                     font=(FONT_FAMILY, FONT_SIZE_NORMAL, "bold"),
                                     fg_color=COLOR_BUTTON_BG, hover_color=COLOR_BUTTON_BG,
                                     text_color=COLOR_TEXT_PRIMARY,
                                     width=110, height=32,
                                     command=self.reset_roi)
        self.btn_roi.pack(side="left", padx=5, pady=10)
        ToolTip(self.btn_roi, "重新选择监控区域（ROI）\n快捷键: Ctrl+R")

        self.btn_shot = ctk.CTkButton(ctrl_frame, text="📷 手动抓拍",
                                      font=(FONT_FAMILY, FONT_SIZE_NORMAL, "bold"),
                                      fg_color=COLOR_BUTTON_BG, hover_color=COLOR_BUTTON_BG,
                                      text_color=COLOR_TEXT_PRIMARY,
                                      width=110, height=32,
                                      command=self.manual_snapshot)
        self.btn_shot.pack(side="left", padx=5, pady=10)
        ToolTip(self.btn_shot, "立即抓拍当前画面\n快捷键: Ctrl+S")

        btn_album = ctk.CTkButton(ctrl_frame, text="📂 相册",
                     font=(FONT_FAMILY, FONT_SIZE_NORMAL, "bold"),
                     fg_color=COLOR_BG_LIGHT, hover_color=COLOR_BG_MEDIUM,
                     text_color=COLOR_TEXT_PRIMARY,
                     width=90, height=32,
                     command=lambda: os.startfile(SCREENSHOT_DIR))
        btn_album.pack(side="right", padx=5, pady=10)
        ToolTip(btn_album, "打开截图文件夹")

        btn_cleanup = ctk.CTkButton(ctrl_frame, text="🗑️ 清理",
                     font=(FONT_FAMILY, FONT_SIZE_NORMAL, "bold"),
                     fg_color=COLOR_BG_LIGHT, hover_color=COLOR_BG_MEDIUM,
                     text_color=COLOR_TEXT_PRIMARY,
                     width=90, height=32,
                     command=self.manual_cleanup)
        btn_cleanup.pack(side="right", padx=5, pady=10)
        ToolTip(btn_cleanup, f"删除{self.config.get('cleanup_days', 3)}天前的截图")

        # 2. 中间显示区 - 使用PanedWindow实现可调整布局
        self.paned_window = tk.PanedWindow(self.root,
                                           orient=tk.HORIZONTAL,
                                           sashwidth=8,
                                           sashrelief=tk.RAISED,
                                           bg=COLOR_BG_MEDIUM,
                                           bd=0)
        self.paned_window.pack(fill="both", expand=True, padx=15, pady=5)

        # 左侧视频 - 使用CTkFrame包装
        video_container = ctk.CTkFrame(self.paned_window, corner_radius=10)
        self.paned_window.add(video_container, minsize=600)

        # 视频标题
        video_header = ctk.CTkFrame(video_container, height=40, corner_radius=8, fg_color=COLOR_BG_DARK)
        video_header.pack(fill="x", padx=5, pady=5)
        ctk.CTkLabel(video_header, text="🎥 实时监控画面",
                    font=(FONT_FAMILY, FONT_SIZE_TITLE, "bold"),
                    text_color=COLOR_TEXT_BLUE).pack(side="left", padx=15, pady=5)

        # 视频显示区（保留tk.Label用于PhotoImage）
        self.lbl_video = tk.Label(video_container, bg=COLOR_BG_DARK, text="[ 等待启动 ]",
                                 fg=COLOR_TEXT_SECONDARY, font=(FONT_FAMILY, FONT_SIZE_LARGE, "bold"))
        self.lbl_video.pack(fill="both", expand=True, padx=5, pady=5)

        # 视频画面右键菜单
        self.video_context_menu = tk.Menu(self.lbl_video, tearoff=0,
                                          bg=COLOR_BG_MEDIUM, fg="white",
                                          activebackground=COLOR_BUTTON_BG, activeforeground="white")
        self.video_context_menu.add_command(label="📷 手动截图", command=self.manual_snapshot)
        self.video_context_menu.add_command(label="◪ 重设ROI", command=self.reset_roi)
        self.lbl_video.bind("<Button-3>", self.show_video_context_menu)

        # 右侧控制区 - 使用滚动框架
        right_container = ctk.CTkFrame(self.paned_window, width=400, corner_radius=10)
        self.paned_window.add(right_container, minsize=350)
        right_container.pack_propagate(False)

        # 创建可滚动框架
        right_panel = ctk.CTkScrollableFrame(right_container, width=380, corner_radius=8)
        right_panel.pack(fill="both", expand=True, padx=5, pady=5)

        # 参数调节面板
        param_frame = ctk.CTkFrame(right_panel, corner_radius=8)
        param_frame.pack(fill="x", pady=(0, 10))

        # 标题
        ctk.CTkLabel(param_frame, text="⚙ 实时参数调节",
                    font=(FONT_FAMILY, FONT_SIZE_TITLE, "bold"),
                    text_color=COLOR_TEXT_BLUE).pack(anchor="w", padx=15, pady=(10, 5))

        # 参数容器
        params_container = ctk.CTkFrame(param_frame, fg_color="transparent")
        params_container.pack(fill="x", padx=10, pady=5)

        # 灵敏度阈值
        sensitivity_frame = ctk.CTkFrame(params_container, fg_color="transparent")
        sensitivity_frame.pack(fill="x", pady=5)
        header1 = ctk.CTkFrame(sensitivity_frame, fg_color="transparent")
        header1.pack(fill="x")
        ctk.CTkLabel(header1, text="灵敏度阈值", font=(FONT_FAMILY, FONT_SIZE_NORMAL, "bold")).pack(side="left")

        # 先创建slider（因为Entry需要引用它）
        self.scale_sensitivity = ctk.CTkSlider(sensitivity_frame, from_=100, to=2000,
                                              command=self.on_sensitivity_change,
                                              button_color=COLOR_BUTTON_BG, button_hover_color=COLOR_BUTTON_BG)
        self.scale_sensitivity.set(self.config['min_area'])

        # 创建可编辑的数值Entry
        self.lbl_sensitivity = self.create_editable_value_entry(
            header1,
            self.config['min_area'],
            self.scale_sensitivity,
            self.on_sensitivity_change
        )
        self.lbl_sensitivity.pack(side="right")

        self.scale_sensitivity.pack(fill="x", pady=(3, 0))
        # 添加Tooltip
        ToolTip(self.scale_sensitivity, "检测运动物体的最小面积（像素²）\n数值越小越灵敏，越容易触发报警\n点击数值可直接输入")
        ToolTip(self.lbl_sensitivity, "点击可直接编辑数值\n按Enter保存，ESC取消")

        # 连续检测帧数
        frames_frame = ctk.CTkFrame(params_container, fg_color="transparent")
        frames_frame.pack(fill="x", pady=5)
        header2 = ctk.CTkFrame(frames_frame, fg_color="transparent")
        header2.pack(fill="x")
        ctk.CTkLabel(header2, text="连续检测帧数", font=(FONT_FAMILY, FONT_SIZE_NORMAL, "bold")).pack(side="left")

        # 先创建slider
        self.scale_frames = ctk.CTkSlider(frames_frame, from_=1, to=10,
                                         command=self.on_frames_change,
                                         button_color=COLOR_BUTTON_BG, button_hover_color=COLOR_BUTTON_BG)
        self.scale_frames.set(self.config['continuous_frames'])

        # 创建可编辑的数值Entry
        self.lbl_frames = self.create_editable_value_entry(
            header2,
            self.config['continuous_frames'],
            self.scale_frames,
            self.on_frames_change
        )
        self.lbl_frames.pack(side="right")

        self.scale_frames.pack(fill="x", pady=(3, 0))
        ToolTip(self.scale_frames, "需要连续检测到运动的帧数才触发报警\n防止误报，数值越大越不容易触发")
        ToolTip(self.lbl_frames, "点击可直接编辑数值\n按Enter保存，ESC取消")

        # 二值化阈值
        threshold_frame = ctk.CTkFrame(params_container, fg_color="transparent")
        threshold_frame.pack(fill="x", pady=5)
        header3 = ctk.CTkFrame(threshold_frame, fg_color="transparent")
        header3.pack(fill="x")
        ctk.CTkLabel(header3, text="二值化阈值", font=(FONT_FAMILY, FONT_SIZE_NORMAL, "bold")).pack(side="left")

        # 先创建slider
        self.scale_threshold = ctk.CTkSlider(threshold_frame, from_=10, to=50,
                                            command=self.on_threshold_change,
                                            button_color=COLOR_BUTTON_BG, button_hover_color=COLOR_BUTTON_BG)
        self.scale_threshold.set(self.config['threshold'])

        # 创建可编辑的数值Entry
        self.lbl_threshold = self.create_editable_value_entry(
            header3,
            self.config['threshold'],
            self.scale_threshold,
            self.on_threshold_change
        )
        self.lbl_threshold.pack(side="right")

        self.scale_threshold.pack(fill="x", pady=(3, 0))
        ToolTip(self.scale_threshold, "图像处理的灰度差异阈值\n数值越小对细微变化越敏感")
        ToolTip(self.lbl_threshold, "点击可直接编辑数值\n按Enter保存，ESC取消")

        # 报警冷却时间
        cooldown_frame = ctk.CTkFrame(params_container, fg_color="transparent")
        cooldown_frame.pack(fill="x", pady=5)
        header4 = ctk.CTkFrame(cooldown_frame, fg_color="transparent")
        header4.pack(fill="x")
        ctk.CTkLabel(header4, text="报警冷却 (秒)", font=(FONT_FAMILY, FONT_SIZE_NORMAL, "bold")).pack(side="left")

        # 先创建slider
        self.scale_cooldown = ctk.CTkSlider(cooldown_frame, from_=1, to=10,
                                           command=self.on_cooldown_change,
                                           button_color=COLOR_BUTTON_BG, button_hover_color=COLOR_BUTTON_BG)
        self.scale_cooldown.set(self.config['alert_cooldown'])

        # 创建可编辑的数值Entry
        self.lbl_cooldown = self.create_editable_value_entry(
            header4,
            self.config['alert_cooldown'],
            self.scale_cooldown,
            self.on_cooldown_change
        )
        self.lbl_cooldown.pack(side="right")

        self.scale_cooldown.pack(fill="x", pady=(3, 0))
        ToolTip(self.scale_cooldown, "两次报警之间的最小间隔时间\n防止频繁报警")
        ToolTip(self.lbl_cooldown, "点击可直接编辑数值\n按Enter保存，ESC取消")

        # 目标帧率
        fps_frame = ctk.CTkFrame(params_container, fg_color="transparent")
        fps_frame.pack(fill="x", pady=5)
        header5 = ctk.CTkFrame(fps_frame, fg_color="transparent")
        header5.pack(fill="x")
        ctk.CTkLabel(header5, text="目标帧率 (FPS)", font=(FONT_FAMILY, FONT_SIZE_NORMAL, "bold")).pack(side="left")
        current_target_fps = int(1.0 / self.config['loop_delay']) if self.config['loop_delay'] > 0 else 5

        # 先创建slider
        self.scale_target_fps = ctk.CTkSlider(fps_frame, from_=5, to=30,
                                             command=self.on_target_fps_change,
                                             button_color=COLOR_BUTTON_BG, button_hover_color=COLOR_BUTTON_BG)
        self.scale_target_fps.set(current_target_fps)

        # 创建可编辑的数值Entry
        self.lbl_target_fps = self.create_editable_value_entry(
            header5,
            current_target_fps,
            self.scale_target_fps,
            self.on_target_fps_change
        )
        self.lbl_target_fps.pack(side="right")

        self.scale_target_fps.pack(fill="x", pady=(3, 0))
        ToolTip(self.scale_target_fps, "视频处理的目标帧率\n数值越低CPU占用越少，适合后台运行")
        ToolTip(self.lbl_target_fps, "点击可直接编辑数值\n按Enter保存，ESC取消")

        # 自定义预设
        ctk.CTkLabel(param_frame, text="自定义预设",
                    font=(FONT_FAMILY, FONT_SIZE_NORMAL, "bold"),
                    text_color=COLOR_WARNING).pack(anchor="w", padx=15, pady=(15, 5))

        presets_container = ctk.CTkFrame(param_frame, fg_color="transparent")
        presets_container.pack(fill="x", padx=10, pady=5)

        # 下拉菜单
        self.preset_combo = ctk.CTkComboBox(presets_container,
                                            values=["无自定义预设"],
                                            state="readonly",
                                            font=(FONT_FAMILY, FONT_SIZE_NORMAL))
        self.preset_combo.pack(fill="x", pady=(0, 5))
        ToolTip(self.preset_combo, "选择一个已保存的预设方案")
        
        # 按钮行
        preset_btn_frame = ctk.CTkFrame(presets_container, fg_color="transparent")
        preset_btn_frame.pack(fill="x")
        # 配置列权重，以便同步缩放
        preset_btn_frame.grid_columnconfigure((0, 1, 2), weight=1)

        self.btn_load_preset = ctk.CTkButton(preset_btn_frame, text="载入",
                     font=(FONT_FAMILY, FONT_SIZE_NORMAL, "bold"),
                     fg_color=COLOR_BUTTON_BG, hover_color=COLOR_BUTTON_BG,
                     text_color=COLOR_TEXT_PRIMARY,
                     text_color_disabled="#E0E0E0", # 修正禁用颜色
                     height=32,
                     command=self._load_preset)
        self.btn_load_preset.grid(row=0, column=0, sticky="ew", padx=(0, 2))
        ToolTip(self.btn_load_preset, "加载选中的预设方案")

        self.btn_save_preset = ctk.CTkButton(preset_btn_frame, text="保存",
                     font=(FONT_FAMILY, FONT_SIZE_NORMAL, "bold"),
                     fg_color=COLOR_BUTTON_BG, hover_color=COLOR_BUTTON_BG,
                     text_color=COLOR_TEXT_PRIMARY,
                     height=32,
                     command=self._save_preset)
        self.btn_save_preset.grid(row=0, column=1, sticky="ew", padx=2)
        ToolTip(self.btn_save_preset, "将当前参数保存为一个新的预设方案")

        self.btn_delete_preset = ctk.CTkButton(preset_btn_frame, text="删除",
                     font=(FONT_FAMILY, FONT_SIZE_NORMAL, "bold"),
                     fg_color=COLOR_BUTTON_BG, hover_color=COLOR_BUTTON_BG, # 恢复蓝色
                     text_color=COLOR_TEXT_PRIMARY,
                     text_color_disabled="#E0E0E0", # 修正禁用颜色
                     height=32,
                     command=self._delete_preset)
        self.btn_delete_preset.grid(row=0, column=2, sticky="ew", padx=(2, 0))
        ToolTip(self.btn_delete_preset, "删除选中的预设方案")

        # 音效设置
        ctk.CTkLabel(param_frame, text="🔊 报警音效",
                    font=(FONT_FAMILY, FONT_SIZE_NORMAL, "bold"),
                    text_color=COLOR_WARNING).pack(anchor="w", padx=15, pady=(15, 5))

        sound_container = ctk.CTkFrame(param_frame, fg_color="transparent")
        sound_container.pack(fill="x", padx=10, pady=5)

        # 启用/禁用音效
        sound_check = ctk.CTkCheckBox(sound_container, text="启用声音",
                                      font=(FONT_FAMILY, FONT_SIZE_NORMAL, "bold"),
                                      fg_color=COLOR_BUTTON_BG,
                                      hover_color=COLOR_BUTTON_BG,
                                      variable=self.sound_enabled)
        sound_check.pack(anchor="w", pady=5)
        ToolTip(sound_check, "开启/关闭报警音效")

        # 音效类型选择
        sound_type_frame = ctk.CTkFrame(sound_container, fg_color="transparent")
        sound_type_frame.pack(fill="x", pady=5)
        ctk.CTkLabel(sound_type_frame, text="音效类型:",
                    font=(FONT_FAMILY, FONT_SIZE_NORMAL, "bold")).pack(side="left", padx=(0, 10))
        sound_combo = ctk.CTkComboBox(sound_type_frame,
                                     variable=self.sound_type,
                                     values=["标准警报", "急促警报", "柔和提示", "双音警报", "三音警报"],
                                     state="readonly",
                                     font=(FONT_FAMILY, FONT_SIZE_NORMAL),
                                     width=150)
        sound_combo.pack(side="left", fill="x", expand=True)
        ToolTip(sound_combo, "选择报警时播放的声音类型\n从柔和到急促，可根据需求选择")

        # 测试音效按钮
        btn_test_sound = ctk.CTkButton(sound_container, text="🔊 测试音效",
                     font=(FONT_FAMILY, FONT_SIZE_NORMAL, "bold"),
                     fg_color=COLOR_BUTTON_BG, hover_color=COLOR_BUTTON_BG,
                     text_color=COLOR_TEXT_PRIMARY,
                     height=30,
                     command=self.test_sound)
        btn_test_sound.pack(fill="x", pady=(5, 10))
        ToolTip(btn_test_sound, "播放当前选择的音效进行试听")

        # 性能统计面板
        stats_frame = ctk.CTkFrame(right_panel, corner_radius=8)
        stats_frame.pack(fill="x", pady=(0, 10))

        # 标题
        ctk.CTkLabel(stats_frame, text="📊 性能监控",
                    font=(FONT_FAMILY, FONT_SIZE_TITLE, "bold"),
                    text_color=COLOR_TEXT_BLUE).pack(anchor="w", padx=15, pady=(10, 5))

        # 统计容器
        stats_container = ctk.CTkFrame(stats_frame, fg_color="transparent")
        stats_container.pack(fill="x", padx=10, pady=5)

        # 运行时长
        runtime_row = ctk.CTkFrame(stats_container, fg_color="transparent", height=30)
        runtime_row.pack(fill="x", pady=3)
        ctk.CTkLabel(runtime_row, text="⏱ 运行时长:",
                    font=(FONT_FAMILY, FONT_SIZE_NORMAL, "bold")).pack(side="left")
        self.lbl_runtime = ctk.CTkLabel(runtime_row, text="00:00:00",
                                       font=(FONT_MONO, FONT_SIZE_LARGE, "bold"),
                                       text_color=COLOR_TEXT_BLUE)
        self.lbl_runtime.pack(side="right")
        ToolTip(self.lbl_runtime, "监控系统已运行的总时长")

        # FPS
        fps_row = ctk.CTkFrame(stats_container, fg_color="transparent", height=30)
        fps_row.pack(fill="x", pady=3)
        ctk.CTkLabel(fps_row, text="📈 实时FPS:",
                    font=(FONT_FAMILY, FONT_SIZE_NORMAL, "bold")).pack(side="left")
        self.lbl_fps_stat = ctk.CTkLabel(fps_row, text="0.0",
                                        font=(FONT_MONO, FONT_SIZE_LARGE, "bold"),
                                        text_color=COLOR_SUCCESS)
        self.lbl_fps_stat.pack(side="right")
        ToolTip(self.lbl_fps_stat, "当前视频处理的帧率\n数值越高表示处理越流畅")

        # 报警次数
        alerts_row = ctk.CTkFrame(stats_container, fg_color="transparent", height=30)
        alerts_row.pack(fill="x", pady=3)
        ctk.CTkLabel(alerts_row, text="⚠ 报警次数:",
                    font=(FONT_FAMILY, FONT_SIZE_NORMAL, "bold")).pack(side="left")
        self.lbl_alerts_stat = ctk.CTkLabel(alerts_row, text="0",
                                           font=(FONT_MONO, FONT_SIZE_LARGE, "bold"),
                                           text_color=COLOR_DANGER)
        self.lbl_alerts_stat.pack(side="right")
        ToolTip(self.lbl_alerts_stat, "检测到运动并触发的报警总次数")

        # 截图总数
        screenshots_row = ctk.CTkFrame(stats_container, fg_color="transparent", height=30)
        screenshots_row.pack(fill="x", pady=3)
        ctk.CTkLabel(screenshots_row, text="📷 截图总数:",
                    font=(FONT_FAMILY, FONT_SIZE_NORMAL, "bold")).pack(side="left")
        self.lbl_screenshots_stat = ctk.CTkLabel(screenshots_row, text="0",
                                                font=(FONT_MONO, FONT_SIZE_LARGE, "bold"),
                                                text_color=COLOR_WARNING)
        self.lbl_screenshots_stat.pack(side="right")
        ToolTip(self.lbl_screenshots_stat, "已保存的截图总数\n包括自动抓拍和手动抓拍")

        # 连续检测
        motion_row = ctk.CTkFrame(stats_container, fg_color="transparent", height=30)
        motion_row.pack(fill="x", pady=(3, 10))
        ctk.CTkLabel(motion_row, text="🎯 连续检测:",
                    font=(FONT_FAMILY, FONT_SIZE_NORMAL, "bold")).pack(side="left")
        self.lbl_motion_stat = ctk.CTkLabel(motion_row, text="0/3",
                                           font=(FONT_MONO, FONT_SIZE_LARGE, "bold"),
                                           text_color=COLOR_TEXT_BLUE)
        self.lbl_motion_stat.pack(side="right")
        ToolTip(self.lbl_motion_stat, "当前连续检测到运动的帧数\n达到设定的连续帧数后将触发报警")

        # 报警历史面板
        alert_history_frame = ctk.CTkFrame(right_panel, corner_radius=8)
        alert_history_frame.pack(fill="x", pady=(0, 10))

        # 标题
        ctk.CTkLabel(alert_history_frame, text="⚠ 报警历史",
                    font=(FONT_FAMILY, FONT_SIZE_TITLE, "bold"),
                    text_color=COLOR_DANGER).pack(anchor="w", padx=15, pady=(10, 5))

        # Treeview容器（使用tk Frame包装以匹配深色主题）
        tree_container = tk.Frame(alert_history_frame, bg=COLOR_BG_MEDIUM)
        tree_container.pack(fill="x", padx=10, pady=(5, 10))

        # 创建Treeview显示报警记录
        columns = ("time", "frames", "screenshots")
        self.alert_tree = tk.ttk.Treeview(tree_container, columns=columns, show="headings",
                                         height=5, style="Custom.Treeview")

        # 配置Treeview样式（深色主题）
        style = tk.ttk.Style()
        style.theme_use("default")
        style.configure("Custom.Treeview",
                       background=COLOR_BG_MEDIUM,
                       foreground="white",
                       fieldbackground=COLOR_BG_MEDIUM,
                       borderwidth=0,
                       font=(FONT_FAMILY, FONT_SIZE_NORMAL))
        style.configure("Custom.Treeview.Heading",
                       background="#1e1e1e",
                       foreground=COLOR_TEXT_BLUE,
                       relief="flat",
                       font=(FONT_FAMILY, FONT_SIZE_NORMAL, "bold"))
        style.map("Custom.Treeview",
                 background=[("selected", COLOR_BUTTON_BG)])

        self.alert_tree.heading("time", text="时间")
        self.alert_tree.heading("frames", text="帧数")
        self.alert_tree.heading("screenshots", text="截图")

        self.alert_tree.column("time", width=100, anchor="center")
        self.alert_tree.column("frames", width=70, anchor="center")
        self.alert_tree.column("screenshots", width=70, anchor="center")

        self.alert_tree.pack(side="left", fill="both", expand=True)
        ToolTip(self.alert_tree, "显示所有报警记录\n双击记录可查看对应的截图")

        # 滚动条
        alert_scrollbar = tk.ttk.Scrollbar(tree_container, orient="vertical",
                                          command=self.alert_tree.yview)
        alert_scrollbar.pack(side="right", fill="y")
        self.alert_tree.configure(yscrollcommand=alert_scrollbar.set)

        # 双击查看截图
        self.alert_tree.bind("<Double-1>", self.on_alert_double_click)

        # 右键菜单
        self.alert_context_menu = tk.Menu(self.alert_tree, tearoff=0,
                                          bg=COLOR_BG_MEDIUM, fg="white",
                                          activebackground=COLOR_BUTTON_BG, activeforeground="white")
        self.alert_context_menu.add_command(label="查看截图", command=self.view_alert_screenshots)
        self.alert_context_menu.add_command(label="删除记录", command=self.delete_alert_record)
        self.alert_context_menu.add_separator()
        self.alert_context_menu.add_command(label="清空全部", command=self.clear_all_alerts)
        self.alert_tree.bind("<Button-3>", self.show_alert_context_menu)

        # 运行日志
        log_frame = ctk.CTkFrame(right_panel, corner_radius=8)
        log_frame.pack(fill="both", expand=True)

        # 标题
        ctk.CTkLabel(log_frame, text="📝 运行日志",
                    font=(FONT_FAMILY, FONT_SIZE_TITLE, "bold"),
                    text_color=COLOR_SUCCESS).pack(anchor="w", padx=15, pady=(10, 5))

        # 使用CTkTextbox替代ScrolledText
        self.txt_log = ctk.CTkTextbox(log_frame,
                                      font=(FONT_MONO, FONT_SIZE_NORMAL),
                                      fg_color=COLOR_BG_DARK,
                                      text_color=COLOR_TEXT_SECONDARY,
                                      wrap="word",
                                      activate_scrollbars=True)
        self.txt_log.pack(fill="both", expand=True, padx=10, pady=(5, 10))
        ToolTip(self.txt_log, "显示系统运行的实时日志\n记录启动、停止、报警等关键事件")

        # 右键菜单
        self.log_context_menu = tk.Menu(self.txt_log, tearoff=0,
                                        bg=COLOR_BG_MEDIUM, fg="white",
                                        activebackground=COLOR_BUTTON_BG, activeforeground="white")
        self.log_context_menu.add_command(label="复制全部", command=self.copy_log)
        self.log_context_menu.add_command(label="清空日志", command=self.clear_log)
        self.log_context_menu.add_separator()
        self.log_context_menu.add_command(label="导出日志", command=self.export_log)
        self.txt_log.bind("<Button-3>", self.show_log_context_menu)

        # 3. 底部状态栏
        status_frame = ctk.CTkFrame(self.root, corner_radius=0, height=35)
        status_frame.pack(side="bottom", fill="x")
        status_frame.pack_propagate(False)

        self.status_var = tk.StringVar(value="● 系统就绪")
        status_label = ctk.CTkLabel(status_frame,
                                   textvariable=self.status_var,
                                   font=(FONT_FAMILY, FONT_SIZE_NORMAL, "bold"),
                                   text_color=COLOR_SUCCESS,
                                   anchor="w")
        status_label.pack(side="left", padx=20, pady=5)

        # 快捷键提示
        ctk.CTkLabel(status_frame,
                    text="快捷键: Space(启停) | Ctrl+S(截图) | Ctrl+R(ROI) | Ctrl+1/2/3(预设)",
                    font=(FONT_MONO, FONT_SIZE_SMALL),
                    text_color=COLOR_TEXT_SECONDARY,
                    anchor="e").pack(side="right", padx=20, pady=5)

        # 4. 绑定快捷键
        self.root.bind("<space>", self.hotkey_toggle_monitoring)
        self.root.bind("<Control-s>", self.hotkey_snapshot)
        self.root.bind("<Control-r>", self.hotkey_reset_roi)
        self.root.bind("<Control-Key-1>", lambda e: self.apply_preset("high"))
        self.root.bind("<Control-Key-2>", lambda e: self.apply_preset("standard"))
        self.root.bind("<Control-Key-3>", lambda e: self.apply_preset("low"))

        # 5. 绑定焦点自动恢复（解决按钮点击后快捷键失效问题）
        self._setup_focus_recovery()

        # 6. 绑定窗口状态变化事件（用于性能优化）
        self.root.bind("<Map>", self.on_window_show)      # 窗口显示
        self.root.bind("<Unmap>", self.on_window_hide)    # 窗口隐藏

        # 启动窗口可见性监控（备用方案，处理某些边界情况）
        self.check_window_visibility()

    def _setup_focus_recovery(self):
        """设置所有按钮的焦点自动恢复功能"""
        def restore_focus(event):
            # 短暂延迟后恢复主窗口焦点
            self.root.after(100, lambda: self.root.focus_force())

        # 递归查找所有按钮
        def bind_buttons(widget):
            for child in widget.winfo_children():
                # 检查是否是按钮（包括CustomTkinter按钮）
                if isinstance(child, (tk.Button, ctk.CTkButton)):
                    # 绑定按钮释放事件（点击完成后）
                    child.bind("<ButtonRelease-1>", restore_focus, add="+")
                # 递归处理子组件
                bind_buttons(child)

        bind_buttons(self.root)

    def check_window_visibility(self):
        """定期检查窗口可见性（备用方案）"""
        try:
            # 检查窗口是否最小化或不可见
            is_visible = (self.root.state() != 'iconic' and self.root.winfo_viewable())
            self.window_visible = is_visible
        except:
            self.window_visible = True

        # 每秒检查一次
        self.root.after(1000, self.check_window_visibility)

    def on_window_show(self, event=None):
        """窗口显示时的回调（立即响应）"""
        self.window_visible = True

    def on_window_hide(self, event=None):
        """窗口隐藏时的回调（立即响应）"""
        self.window_visible = False

    def log(self, msg):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        logging.info(msg)
        # CTkTextbox doesn't need state management
        self.txt_log.insert(tk.END, f"[{timestamp}] {msg}\n")
        self.txt_log.see(tk.END)

    def start_monitoring(self):
        if self.is_running: return
        try:
            self.cap = cv2.VideoCapture(self.config['camera_id'])
            if not self.cap.isOpened():
                messagebox.showerror("错误", "无法连接摄像头")
                return

            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

            self.is_running = True
            self.is_paused = False
            self.motion_frame_count = 0
            self.start_time = time.time()  # 记录启动时间

            # 按钮状态更新
            self.btn_start.configure(state="disabled")
            self.btn_stop.configure(state="normal")
            self.btn_pause.configure(state="normal")
            self.status_var.set("正在运行")
            self.log("监控服务已启动")

            # 启动线程
            Thread(target=self.video_loop, daemon=True).start()

        except Exception as e:
            self.log(f"启动异常: {e}")

    def stop_monitoring(self):
        self.is_running = False
        if self.cap: self.cap.release()
        self.lbl_video.configure(image='', text="[ 监控已停止 ]", bg=COLOR_BG_DARK)
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.btn_pause.configure(state="disabled", text="⏸ 暂停")
        self.status_var.set("已停止")
        self.log("监控服务已停止")

    def toggle_pause(self):
        self.is_paused = not self.is_paused
        text = "▶ 继续" if self.is_paused else "⏸ 暂停"
        self.btn_pause.configure(text=text)
        status = "已暂停" if self.is_paused else "监控中"
        self.status_var.set(status)
        self.log(f"用户操作: {status}")
        if not self.is_paused:
            self.motion_frame_count = 0 # 恢复时重置计数

    def reset_roi(self):
        if not self.is_running:
            messagebox.showinfo("提示", "请先启动监控")
            return

        # 检查是否已经在选择中
        if self.roi_selecting:
            self.log("ROI选择正在进行中，请稍候...")
            return

        # 使用 OpenCV 原生窗口进行选择 (按照你的脚本逻辑，这是最稳健的)
        Thread(target=self._roi_selector_thread, daemon=True).start()

    def _roi_selector_thread(self):
        # 设置选择中标志
        self.roi_selecting = True
        self.log("请在弹出的窗口中拖动鼠标选择区域...")

        # 暂时暂停检测，避免干扰
        was_paused = self.is_paused
        self.is_paused = True

        try:
            # 等待video_loop停止显示
            time.sleep(0.2)

            ret, frame = self.cap.read()
            if ret:
                # 使用Tkinter选择器（避免OpenCV窗口问题）
                self.root.after(0, lambda: self._show_tkinter_roi_selector(frame, was_paused))
            else:
                self.log("无法读取画面")
                self.roi_selecting = False
                self.is_paused = was_paused

        except Exception as e:
            self.log(f"ROI选择出错: {e}")
            import traceback
            logging.error(traceback.format_exc())
            self.roi_selecting = False
            self.is_paused = was_paused

    def _show_tkinter_roi_selector(self, frame, was_paused):
        """使用Tkinter实现的ROI选择器"""
        # 创建选择窗口
        selector_win = tk.Toplevel(self.root)
        selector_win.title("ROI区域选择 - 拖动鼠标框选区域")
        selector_win.attributes('-topmost', True)

        # 转换图像
        cv2image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(cv2image)
        imgtk = ImageTk.PhotoImage(image=img)

        # 创建Canvas
        canvas = tk.Canvas(selector_win, width=img.width, height=img.height, cursor="cross")
        canvas.pack()
        canvas.create_image(0, 0, anchor="nw", image=imgtk)
        canvas.imgtk = imgtk  # 防止被垃圾回收

        # ROI选择变量
        roi_data = {'start_x': None, 'start_y': None, 'rect': None, 'confirmed': False, 'roi': None}

        def on_mouse_down(event):
            roi_data['start_x'] = event.x
            roi_data['start_y'] = event.y
            if roi_data['rect']:
                canvas.delete(roi_data['rect'])

        def on_mouse_drag(event):
            if roi_data['start_x'] is not None:
                if roi_data['rect']:
                    canvas.delete(roi_data['rect'])
                roi_data['rect'] = canvas.create_rectangle(
                    roi_data['start_x'], roi_data['start_y'],
                    event.x, event.y,
                    outline='#00FF00', width=2
                )

        def on_mouse_up(event):
            if roi_data['start_x'] is not None:
                x1, y1 = roi_data['start_x'], roi_data['start_y']
                x2, y2 = event.x, event.y

                # 确保坐标正确（左上到右下）
                x = min(x1, x2)
                y = min(y1, y2)
                w = abs(x2 - x1)
                h = abs(y2 - y1)

                roi_data['roi'] = (x, y, w, h)

        def confirm_selection():
            roi_data['confirmed'] = True
            selector_win.destroy()

        def cancel_selection():
            roi_data['confirmed'] = False
            roi_data['roi'] = None
            selector_win.destroy()

        # 绑定事件
        canvas.bind("<ButtonPress-1>", on_mouse_down)
        canvas.bind("<B1-Motion>", on_mouse_drag)
        canvas.bind("<ButtonRelease-1>", on_mouse_up)

        # 创建按钮
        btn_frame = tk.Frame(selector_win)
        btn_frame.pack(fill='x', pady=5)

        ttk.Label(btn_frame, text="拖动鼠标框选区域，然后点击确认", font=(FONT_FAMILY, FONT_SIZE_SMALL)).pack(side='left', padx=10)
        ttk.Button(btn_frame, text="✓ 确认 (Enter)", command=confirm_selection).pack(side='right', padx=5)
        ttk.Button(btn_frame, text="✗ 取消 (ESC)", command=cancel_selection).pack(side='right', padx=5)

        # 绑定快捷键（阻止事件传播）
        def on_enter(e):
            confirm_selection()
            return "break"  # 阻止事件传播

        def on_escape(e):
            cancel_selection()
            return "break"  # 阻止事件传播

        selector_win.bind("<Return>", on_enter)
        selector_win.bind("<Escape>", on_escape)

        # 窗口关闭时的处理
        def on_close():
            roi_data['confirmed'] = False
            roi_data['roi'] = None
            selector_win.destroy()

        selector_win.protocol("WM_DELETE_WINDOW", on_close)

        # 让选择窗口获得焦点
        selector_win.focus_force()

        # 等待窗口关闭
        selector_win.wait_window()

        # 窗口关闭后，恢复主窗口焦点
        self.root.focus_force()

        # 处理结果
        if roi_data['confirmed'] and roi_data['roi']:
            x, y, w, h = roi_data['roi']
            if w > 0 and h > 0:
                self.config['roi'] = (x, y, w, h)
                self.save_config()
                self.roi_reset_flag = True
                self.motion_frame_count = 0
                self.log(f"ROI 更新成功: ({x}, {y}, {w}, {h})")
                self.update_sensitivity_range((x, y, w, h))
            else:
                self.log("选择区域无效（太小）")
        else:
            self.log("取消区域设置")

        # 恢复状态
        self.roi_selecting = False
        self.is_paused = was_paused
        self.log("ROI选择流程完成")

    def save_screenshot(self, frame, prefix="manual", seq=None):
        """严格按照你的脚本逻辑，支持中文路径"""
        try:
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            suffix = f"_{seq}" if seq is not None else ""
            filename = f"{prefix}_{timestamp}{suffix}.jpg"
            filepath = os.path.join(SCREENSHOT_DIR, filename)

            success, encoded_img = cv2.imencode('.jpg', frame)
            if success:
                with open(filepath, 'wb') as f:
                    f.write(encoded_img.tobytes())
                self.screenshot_count += 1
                self.log(f"截图保存: {filename}")
                return filepath  # 返回文件路径
        except Exception as e:
            self.log(f"截图失败: {e}")
        return None

    def capture_burst(self):
        """连续抓拍逻辑"""
        screenshots = []
        count = self.config.get('screenshot_count', 3)
        interval = self.config.get('screenshot_interval', 0.5)
        for i in range(count):
            if not self.is_running: break
            if self.cap:
                ret, frame = self.cap.read()
                if ret:
                    filepath = self.save_screenshot(frame, "alert", i+1)
                    if filepath:
                        screenshots.append(filepath)
            time.sleep(interval)
        return screenshots

    def manual_snapshot(self):
        if self.is_running and self.cap:
            ret, frame = self.cap.read()
            if ret: self.save_screenshot(frame, "manual")

    def cleanup_old_screenshots(self):
        """清理旧截图"""
        try:
            if not self.config.get('auto_cleanup_enabled', True):
                return

            cleanup_days = self.config.get('cleanup_days', 3)
            now = time.time()
            cutoff_time = now - (cleanup_days * 24 * 3600)

            deleted_count = 0
            total_size = 0

            for filename in os.listdir(SCREENSHOT_DIR):
                filepath = os.path.join(SCREENSHOT_DIR, filename)
                if os.path.isfile(filepath) and filename.endswith('.jpg'):
                    file_time = os.path.getmtime(filepath)
                    if file_time < cutoff_time:
                        file_size = os.path.getsize(filepath)
                        os.remove(filepath)
                        deleted_count += 1
                        total_size += file_size

            if deleted_count > 0:
                size_mb = total_size / (1024 * 1024)
                self.log(f"清理完成: 删除了{deleted_count}个旧截图，释放{size_mb:.2f}MB空间")
            else:
                self.log(f"清理检查完成: 无需删除截图")

        except Exception as e:
            self.log(f"清理截图失败: {e}")

    def manual_cleanup(self):
        """手动清理旧截图"""
        try:
            from tkinter import messagebox
            cleanup_days = self.config.get('cleanup_days', 3)
            result = messagebox.askyesno("确认清理",
                                        f"确定要删除{cleanup_days}天前的所有截图吗？\n此操作不可恢复！")
            if result:
                self.cleanup_old_screenshots()
        except Exception as e:
            self.log(f"手动清理失败: {e}")

    def perform_memory_cleanup(self):
        """执行内存清理"""
        try:
            import gc
            gc.collect()
            # 记录内存使用情况（可选）
            # import psutil
            # process = psutil.Process()
            # mem_mb = process.memory_info().rss / (1024 * 1024)
            # self.log(f"内存清理完成，当前使用: {mem_mb:.2f}MB")
        except Exception as e:
            logging.error(f"内存清理失败: {e}")

    # === 右键菜单回调函数 ===

    def show_alert_context_menu(self, event):
        """显示报警历史右键菜单"""
        try:
            self.alert_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.alert_context_menu.grab_release()

    def show_log_context_menu(self, event):
        """显示日志右键菜单"""
        try:
            self.log_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.log_context_menu.grab_release()

    def show_video_context_menu(self, event):
        """显示视频画面右键菜单"""
        try:
            self.video_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.video_context_menu.grab_release()

    def view_alert_screenshots(self):
        """查看选中报警的截图"""
        selection = self.alert_tree.selection()
        if selection:
            item = self.alert_tree.item(selection[0])
            index = self.alert_tree.index(selection[0])
            if index < len(self.alert_history):
                self.on_alert_double_click(None)  # 复用双击功能

    def delete_alert_record(self):
        """删除选中的报警记录"""
        selection = self.alert_tree.selection()
        if selection:
            index = self.alert_tree.index(selection[0])
            if index < len(self.alert_history):
                del self.alert_history[index]
                self.alert_tree.delete(selection[0])
                self.log("已删除选中的报警记录")

    def clear_all_alerts(self):
        """清空所有报警记录"""
        from tkinter import messagebox
        result = messagebox.askyesno("确认清空", "确定要清空所有报警记录吗？")
        if result:
            self.alert_history.clear()
            for item in self.alert_tree.get_children():
                self.alert_tree.delete(item)
            self.log("已清空所有报警记录")

    def copy_log(self):
        """复制所有日志到剪贴板"""
        try:
            log_text = self.txt_log.get("1.0", "end-1c")
            self.root.clipboard_clear()
            self.root.clipboard_append(log_text)
            self.log("日志已复制到剪贴板")
        except Exception as e:
            self.log(f"复制失败: {e}")

    def clear_log(self):
        """清空日志"""
        from tkinter import messagebox
        result = messagebox.askyesno("确认清空", "确定要清空运行日志吗？")
        if result:
            self.txt_log.delete("1.0", "end")
            self.log("日志已清空")

    def export_log(self):
        """导出日志到文件"""
        try:
            from tkinter import filedialog
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            default_name = f"monitor_log_{timestamp}.txt"
            filepath = filedialog.asksaveasfilename(
                defaultextension=".txt",
                filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
                initialfile=default_name
            )
            if filepath:
                log_text = self.txt_log.get("1.0", "end-1c")
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(log_text)
                self.log(f"日志已导出到: {filepath}")
        except Exception as e:
            self.log(f"导出失败: {e}")

    def create_editable_value_entry(self, parent, initial_value, slider_widget, callback, get_range_func=None):
        """创建可原位编辑的数值Entry控件"""
        # 创建Entry，默认样式像Label（使用父容器背景色模拟透明）
        entry = ctk.CTkEntry(parent,
                            width=60,
                            height=25,
                            font=(FONT_MONO, FONT_SIZE_NORMAL, "bold"),
                            text_color=COLOR_TEXT_BLUE,
                            fg_color=COLOR_BG_MEDIUM,  # 使用深色背景而非transparent
                            border_width=0,
                            justify="right")
        entry.insert(0, str(initial_value))

        # 保存原始值，用于取消编辑
        entry.original_value = str(initial_value)
        entry.editing = False

        def on_click(event):
            """点击时进入编辑模式"""
            if not entry.editing:
                entry.editing = True
                entry.configure(fg_color=COLOR_BG_DARK, border_width=2, border_color=COLOR_TEXT_BLUE)
                entry.select_range(0, tk.END)
                entry.focus()

        def on_focus_out(event):
            """失去焦点时保存"""
            save_value()

        def on_enter(event):
            """按Enter键保存"""
            save_value()
            entry.master.focus()  # 移除焦点

        def on_escape(event):
            """按ESC键取消"""
            entry.delete(0, tk.END)
            entry.insert(0, entry.original_value)
            entry.editing = False
            entry.configure(fg_color=COLOR_BG_MEDIUM, border_width=0)
            entry.master.focus()

        def save_value():
            """保存数值"""
            if not entry.editing:
                return

            value_str = entry.get()
            if isinstance(value_str, str):
                value_str = value_str.strip()
            else:
                # CTkEntry可能返回其他类型，转换为字符串
                value_str = str(value_str).strip()

            if not value_str:
                # 空值，恢复原值
                entry.delete(0, tk.END)
                entry.insert(0, entry.original_value)
                entry.editing = False
                entry.configure(fg_color=COLOR_BG_MEDIUM, border_width=0)
                return

            try:
                num_value = float(value_str)

                # 获取有效范围
                if get_range_func:
                    min_val, max_val = get_range_func()
                else:
                    # 从slider获取范围
                    min_val = slider_widget.cget("from_")
                    max_val = slider_widget.cget("to")

                # 验证范围
                if min_val <= num_value <= max_val:
                    # 更新slider
                    slider_widget.set(num_value)
                    # 触发回调
                    if callback:
                        callback(num_value)
                    # 更新Entry显示
                    display_value = int(num_value) if num_value == int(num_value) else num_value
                    entry.delete(0, tk.END)
                    entry.insert(0, str(display_value))
                    entry.original_value = str(display_value)
                    entry.editing = False
                    entry.configure(fg_color=COLOR_BG_MEDIUM, border_width=0)
                else:
                    # 超出范围
                    messagebox.showwarning("数值超出范围",
                                         f"请输入 {int(min_val)} 到 {int(max_val)} 之间的数值")
                    entry.delete(0, tk.END)
                    entry.insert(0, entry.original_value)
                    entry.select_range(0, tk.END)
            except ValueError:
                # 无效数字
                messagebox.showerror("输入错误", "请输入有效的数字")
                entry.delete(0, tk.END)
                entry.insert(0, entry.original_value)
                entry.select_range(0, tk.END)

        # 绑定事件
        entry.bind("<Button-1>", on_click)
        entry.bind("<FocusOut>", on_focus_out)
        entry.bind("<Return>", on_enter)
        entry.bind("<Escape>", on_escape)

        return entry

    def on_sensitivity_change(self, value):
        """灵敏度阈值变化"""
        val = int(float(value))
        self.config['min_area'] = val
        # 更新Entry显示
        if not self.lbl_sensitivity.editing:
            self.lbl_sensitivity.delete(0, tk.END)
            self.lbl_sensitivity.insert(0, str(val))
            self.lbl_sensitivity.original_value = str(val)

    def on_frames_change(self, value):
        """连续帧数变化"""
        val = int(float(value))
        self.config['continuous_frames'] = val
        # 更新Entry显示
        if not self.lbl_frames.editing:
            self.lbl_frames.delete(0, tk.END)
            self.lbl_frames.insert(0, str(val))
            self.lbl_frames.original_value = str(val)
        self.motion_frame_count = 0  # 重置计数

    def on_threshold_change(self, value):
        """二值化阈值变化"""
        val = int(float(value))
        self.config['threshold'] = val
        # 更新Entry显示
        if not self.lbl_threshold.editing:
            self.lbl_threshold.delete(0, tk.END)
            self.lbl_threshold.insert(0, str(val))
            self.lbl_threshold.original_value = str(val)

    def on_cooldown_change(self, value):
        """报警冷却时间变化"""
        val = int(float(value))
        self.config['alert_cooldown'] = val
        # 更新Entry显示
        if not self.lbl_cooldown.editing:
            self.lbl_cooldown.delete(0, tk.END)
            self.lbl_cooldown.insert(0, str(val))
            self.lbl_cooldown.original_value = str(val)

    def on_target_fps_change(self, value):
        """目标帧率变化"""
        val = int(float(value))
        # 更新Entry显示
        if not self.lbl_target_fps.editing:
            self.lbl_target_fps.delete(0, tk.END)
            self.lbl_target_fps.insert(0, str(val))
            self.lbl_target_fps.original_value = str(val)
        # 根据目标FPS计算loop_delay
        self.config['loop_delay'] = 1.0 / val if val > 0 else 0.2

    def play_alert_sound(self):
        """播放报警音效"""
        if not self.sound_enabled.get():
            return  # 音效已禁用

        sound_type = self.sound_type.get()

        try:
            if sound_type == "标准警报":
                # 单音，1000Hz，200ms
                winsound.Beep(1000, 200)

            elif sound_type == "急促警报":
                # 三声短促警报
                for _ in range(3):
                    winsound.Beep(1500, 100)
                    time.sleep(0.05)

            elif sound_type == "柔和提示":
                # 低频柔和提示音
                winsound.Beep(600, 300)

            elif sound_type == "双音警报":
                # 高低交替双音
                winsound.Beep(1200, 150)
                time.sleep(0.1)
                winsound.Beep(800, 150)

            elif sound_type == "三音警报":
                # 三音递增警报
                winsound.Beep(800, 100)
                time.sleep(0.05)
                winsound.Beep(1000, 100)
                time.sleep(0.05)
                winsound.Beep(1200, 150)

        except Exception as e:
            logging.error(f"播放音效失败: {e}")

    def test_sound(self):
        """测试当前选择的音效"""
        Thread(target=self.play_alert_sound, daemon=True).start()

    def update_sensitivity_range(self, roi):
        """根据ROI大小动态调整灵敏度阈值范围"""
        x, y, w, h = roi
        roi_area = w * h

        # 根据ROI面积计算合理的阈值范围
        # 小ROI（<1000像素²）: 50-500
        # 中ROI（1000-5000）: 200-1000
        # 大ROI（>5000）: 500-2000
        if roi_area < 1000:
            min_val, max_val = 50, 500
            recommended = int(roi_area * 0.2)  # 20%的面积
        elif roi_area < 5000:
            min_val, max_val = 200, 1000
            recommended = int(roi_area * 0.15)  # 15%的面积
        else:
            min_val, max_val = 500, 2000
            recommended = int(roi_area * 0.1)  # 10%的面积

        # 更新滑块范围（CustomTkinter使用configure）
        self.scale_sensitivity.configure(from_=min_val, to=max_val)

        # 如果当前值超出新范围，自动调整
        current_val = self.config['min_area']
        if current_val < min_val or current_val > max_val:
            self.scale_sensitivity.set(recommended)
            self.log(f"ROI面积: {roi_area}像素², 推荐阈值: {recommended}, 范围: [{min_val}, {max_val}]")
        else:
            self.log(f"灵敏度范围已更新: [{min_val}, {max_val}], ROI面积: {roi_area}像素²")

    def update_fps(self):
        """更新FPS计算"""
        self.frame_count += 1
        elapsed = time.time() - self.fps_start_time
        if elapsed > 1.0:  # 每秒更新一次
            self.fps = self.frame_count / elapsed
            self.frame_count = 0
            self.fps_start_time = time.time()

    def draw_overlay(self, frame, x: int, y: int, w: int, h: int, motion_detected: bool):
        """在画面上绘制叠加信息（移植自security_monitor.py）"""
        # 绘制ROI矩形框（绿色=正常，红色=检测到运动，橙色=暂停）
        # 注意：OpenCV使用BGR格式，不是RGB
        if motion_detected and not self.is_paused:
            color = (0, 0, 255)  # 红色 (BGR)
        elif self.is_paused:
            color = (0, 165, 255)  # 橙色 (BGR: Blue=0, Green=165, Red=255)
        else:
            color = (0, 255, 0)  # 绿色 (BGR)

        cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)

        # 准备叠加信息
        timestamp = time.strftime('%H:%M:%S')

        if self.is_paused:
            status = "PAUSED"
            status_color = (0, 165, 255)  # 橙色 (BGR)
        elif motion_detected:
            status = "MOTION!"
            status_color = (0, 0, 255)  # 红色 (BGR)
        else:
            status = "Normal"
            status_color = (0, 255, 0)  # 绿色 (BGR)

        # 背景半透明黑色矩形（缩小）
        overlay = frame.copy()
        cv2.rectangle(overlay, (10, 10), (220, 95), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)

        # 绘制文字信息（缩小字体到一半大小，不加粗）
        font = cv2.FONT_HERSHEY_SIMPLEX
        cv2.putText(frame, "Security Monitor", (15, 25), font, 0.4, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(frame, f"Time: {timestamp}", (15, 42), font, 0.33, (230, 230, 230), 1, cv2.LINE_AA)
        cv2.putText(frame, f"Alerts: {self.alert_count} | FPS: {self.fps:.1f}", (15, 59), font, 0.33, (230, 230, 230), 1, cv2.LINE_AA)
        cv2.putText(frame, f"Status: {status}", (15, 76), font, 0.35, status_color, 1, cv2.LINE_AA)
        cv2.putText(frame, f"Motion: {self.motion_frame_count}/{self.config['continuous_frames']}", (15, 90), font, 0.33, (230, 230, 230), 1, cv2.LINE_AA)

    def video_loop(self):
        prev_frame = None
        consecutive_failures = 0
        reconnect_attempts = 0
        max_reconnect_attempts = 3

        while self.is_running:
            ret, frame = self.cap.read()
            if not ret:
                consecutive_failures += 1
                if consecutive_failures > self.config['max_failures']:
                    self.log(f"错误: 摄像头连接失败 ({consecutive_failures}次)")

                    # 尝试重新连接
                    if reconnect_attempts < max_reconnect_attempts:
                        reconnect_attempts += 1
                        self.log(f"尝试重新连接摄像头... (第{reconnect_attempts}次)")
                        time.sleep(2)

                        try:
                            if self.cap:
                                self.cap.release()
                            self.cap = cv2.VideoCapture(self.config['camera_id'])
                            if self.cap.isOpened():
                                self.log("摄像头重新连接成功")
                                consecutive_failures = 0
                                reconnect_attempts = 0
                                continue
                        except Exception as e:
                            self.log(f"重连失败: {e}")

                    self.log("摄像头断开，停止监控")
                    self.stop_monitoring()
                    break
                time.sleep(0.1)
                continue
            consecutive_failures = 0
            reconnect_attempts = 0
            self.update_fps()  # 更新FPS计算

            # 1. 区域处理
            x, y, w, h = 0, 0, frame.shape[1], frame.shape[0]
            if self.config['roi']:
                rx, ry, rw, rh = self.config['roi']
                if validate_roi((rx, ry, rw, rh), frame.shape):
                    x, y, w, h = rx, ry, rw, rh

            motion_detected = False
            
            # 检查是否需要重置（ROI变更）
            if self.roi_reset_flag:
                prev_frame = None
                self.roi_reset_flag = False
                self.log("ROI已重置，重新初始化检测")

            # 2. 核心算法 (严格遵循你的 security_monitor.py)
            if not self.is_paused:
                roi_frame = frame[y:y+h, x:x+w]
                gray = cv2.cvtColor(roi_frame, cv2.COLOR_BGR2GRAY)
                gray = cv2.GaussianBlur(gray, (self.config['gaussian_blur'], self.config['gaussian_blur']), 0)

                if prev_frame is None:
                    prev_frame = gray
                else:
                    frame_delta = cv2.absdiff(prev_frame, gray)
                    thresh = cv2.threshold(frame_delta, self.config['threshold'], 255, cv2.THRESH_BINARY)[1]
                    thresh = cv2.dilate(thresh, None, iterations=self.config['dilate_iterations'])
                    
                    cnts, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    
                    for c in cnts:
                        if cv2.contourArea(c) > self.config['min_area']:
                            motion_detected = True
                            break
                    
                    prev_frame = gray

            # 3. 连续帧防抖逻辑
            if motion_detected:
                self.motion_frame_count += 1
            else:
                self.motion_frame_count = 0

            is_confirmed_motion = self.motion_frame_count >= self.config['continuous_frames']

            # 4. 报警触发
            if is_confirmed_motion:
                current_time = time.time()
                if current_time - self.last_alert_time > self.config['alert_cooldown']:
                    self.last_alert_time = current_time
                    self.alert_count += 1

                    self.log(f"⚠️ 动静检测! (连续{self.motion_frame_count}帧)")
                    self.status_var.set(f"⚠️ 警告: 检测到运动! (#{self.alert_count})")

                    # 显示弹窗提示
                    self.root.after(0, lambda: self.show_alert_popup(self.motion_frame_count))

                    # 播放报警音效
                    Thread(target=self.play_alert_sound, daemon=True).start()

                    # 自动连拍
                    if self.config['auto_screenshot']:
                        def capture_and_record():
                            screenshots = self.capture_burst()
                            self.add_alert_history(self.motion_frame_count, screenshots)
                        Thread(target=capture_and_record, daemon=True).start()
            
            # 5. 界面绘制（使用overlay方法）
            # 性能优化：窗口隐藏时跳过GUI渲染
            if not self.window_visible:
                # 窗口不可见时，跳过所有GUI相关操作以降低CPU使用
                time.sleep(self.config['loop_delay'])
                continue

            display_frame = frame.copy()
            self.draw_overlay(display_frame, x, y, w, h, is_confirmed_motion)

            # 转换显示（ROI选择时跳过）
            if self.roi_selecting:
                time.sleep(self.config['loop_delay'])
                continue

            try:
                # 智能缩放适应窗口
                win_w = self.lbl_video.winfo_width()
                win_h = self.lbl_video.winfo_height()

                if win_w > 10 and win_h > 10:
                    cv2image = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
                    img = Image.fromarray(cv2image)
                    
                    # 保持比例缩放
                    img_ratio = img.width / img.height
                    win_ratio = win_w / win_h
                    if img_ratio > win_ratio:
                        new_w = win_w
                        new_h = int(win_w / img_ratio)
                    else:
                        new_h = win_h
                        new_w = int(win_h * img_ratio)
                    
                    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                    imgtk = ImageTk.PhotoImage(image=img)
                    self.root.after(0, lambda: self.update_video(imgtk))

                # 更新统计面板
                self.root.after(0, self.update_stats)
            except: pass

            # 定期清理和优化
            current_time = time.time()

            # 内存清理（每小时一次）
            if current_time - self.last_memory_cleanup > self.config.get('memory_cleanup_interval', 3600):
                self.perform_memory_cleanup()
                self.last_memory_cleanup = current_time

            # 截图清理（每24小时一次）
            if current_time - self.last_screenshot_cleanup > 86400:
                if self.config.get('auto_cleanup_enabled', True):
                    Thread(target=self.cleanup_old_screenshots, daemon=True).start()
                self.last_screenshot_cleanup = current_time

            time.sleep(self.config['loop_delay'])

    def update_video(self, imgtk):
        self.lbl_video.configure(image=imgtk)
        self.lbl_video.imgtk = imgtk

    def update_stats(self):
        """更新统计面板信息"""
        try:
            # 运行时长
            if self.start_time:
                elapsed = int(time.time() - self.start_time)
                hours = elapsed // 3600
                minutes = (elapsed % 3600) // 60
                seconds = elapsed % 60
                runtime_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                self.lbl_runtime.configure(text=runtime_str)

            # FPS
            self.lbl_fps_stat.configure(text=f"{self.fps:.1f}")

            # 报警次数
            self.lbl_alerts_stat.configure(text=str(self.alert_count))

            # 截图总数
            self.lbl_screenshots_stat.configure(text=str(self.screenshot_count))

            # 连续检测
            motion_str = f"{self.motion_frame_count}/{self.config['continuous_frames']}"
            self.lbl_motion_stat.configure(text=motion_str)

        except Exception as e:
            logging.error(f"更新统计失败: {e}")

    def hotkey_toggle_monitoring(self, event=None):
        """快捷键：启动/暂停监控"""
        if not self.is_running:
            self.start_monitoring()
        else:
            self.toggle_pause()
        return "break"  # 阻止事件传播

    def hotkey_snapshot(self, event=None):
        """快捷键：手动截图"""
        self.manual_snapshot()
        return "break"

    def hotkey_reset_roi(self, event=None):
        """快捷键：重设ROI"""
        self.reset_roi()
        return "break"

    def add_alert_history(self, frames, screenshots):
        """添加报警记录到历史"""
        try:
            timestamp = datetime.datetime.now().strftime('%H:%M:%S')
            record = {
                'time': timestamp,
                'frames': frames,
                'screenshots': screenshots
            }
            self.alert_history.append(record)

            # 更新UI（最多显示20条）
            if len(self.alert_history) > 20:
                self.alert_history.pop(0)

            # 更新Treeview
            self.root.after(0, self._update_alert_tree)

        except Exception as e:
            logging.error(f"添加报警历史失败: {e}")

    def _update_alert_tree(self):
        """更新报警历史Treeview"""
        try:
            # 清空现有项
            for item in self.alert_tree.get_children():
                self.alert_tree.delete(item)

            # 插入记录（倒序显示，最新的在上面）
            for record in reversed(self.alert_history):
                self.alert_tree.insert("", "end", values=(
                    record['time'],
                    f"{record['frames']}帧",
                    f"{len(record['screenshots'])}张"
                ))
        except Exception as e:
            logging.error(f"更新报警历史失败: {e}")

    def on_alert_double_click(self, event):
        """双击报警记录查看截图"""
        try:
            selection = self.alert_tree.selection()
            if not selection:
                return

            # 获取选中项的索引（倒序）
            item = selection[0]
            index = self.alert_tree.index(item)

            # 获取对应的报警记录
            if index < len(self.alert_history):
                record = list(reversed(self.alert_history))[index]
                if record['screenshots']:
                    # 打开截图管理器显示这些截图
                    self.open_screenshot_viewer(record['screenshots'])
                else:
                    messagebox.showinfo("提示", "该报警没有关联的截图")
        except Exception as e:
            logging.error(f"打开报警截图失败: {e}")

    def open_screenshot_viewer(self, screenshots):
        """打开截图管理器窗口"""
        if not screenshots:
            return

        # 创建查看器窗口
        viewer = tk.Toplevel(self.root)
        viewer.title(f"截图管理器 - 共 {len(screenshots)} 张")
        viewer.geometry("1000x700")

        # 主容器：左侧缩略图列表 + 右侧大图预览
        main_container = tk.PanedWindow(viewer, orient=tk.HORIZONTAL, sashwidth=5)
        main_container.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 左侧：缩略图滚动列表
        left_frame = ttk.Frame(main_container)
        main_container.add(left_frame, width=250)

        ttk.Label(left_frame, text="缩略图列表", font=("Arial", 10, "bold")).pack(pady=5)

        canvas_container = ttk.Frame(left_frame)
        canvas_container.pack(fill=tk.BOTH, expand=True)

        thumb_canvas = tk.Canvas(canvas_container, bg="white", width=230)
        thumb_scrollbar = ttk.Scrollbar(canvas_container, orient="vertical", command=thumb_canvas.yview)
        thumb_canvas.configure(yscrollcommand=thumb_scrollbar.set)

        thumb_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        thumb_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        thumb_frame = ttk.Frame(thumb_canvas)
        thumb_canvas.create_window((0, 0), window=thumb_frame, anchor="nw")

        # 右侧：大图预览区
        right_frame = ttk.Frame(main_container)
        main_container.add(right_frame, width=700)

        preview_label = tk.Label(right_frame, text="点击左侧缩略图查看完整截图",
                                font=("Arial", 12), fg="gray", bg=COLOR_BG_MEDIUM)
        preview_label.pack(expand=True)

        # 底部控制栏
        control_frame = ttk.Frame(right_frame)
        control_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=5)

        info_label = ttk.Label(control_frame, text="", font=("Arial", 9))
        info_label.pack(side=tk.LEFT, padx=10)

        # 状态变量
        viewer_state = {
            'current_index': 0,
            'screenshots': screenshots[:],  # 拷贝列表
            'thumb_images': [],  # 保持引用防止被GC
            'preview_image': None
        }

        def load_and_show_image(index):
            """加载并显示指定索引的图片"""
            if not viewer_state['screenshots'] or index >= len(viewer_state['screenshots']):
                self.log("截图查看器: 没有可显示的图片")
                return

            filepath = viewer_state['screenshots'][index]
            self.log(f"截图查看器: 尝试加载图片 {filepath}")

            if not os.path.exists(filepath):
                error_msg = f"文件不存在: {os.path.basename(filepath)}"
                info_label.configure(text=error_msg, foreground="red")
                self.log(f"截图查看器: {error_msg}")
                return

            try:
                # 加载完整图片
                img = Image.open(filepath)
                original_size = img.size
                self.log(f"截图查看器: 图片加载成功，原始尺寸: {original_size}")

                # 缩放以适应预览区域（保持比例）
                max_w, max_h = 680, 600
                # 兼容不同版本的Pillow
                try:
                    img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
                except AttributeError:
                    img.thumbnail((max_w, max_h), Image.LANCZOS)

                self.log(f"截图查看器: 图片缩放后尺寸: {img.size}")

                photo = ImageTk.PhotoImage(img)
                viewer_state['preview_image'] = photo

                # 确保设置image属性
                preview_label.configure(image=photo, text="", compound='center')
                preview_label.image = photo  # 保持引用

                self.log(f"截图查看器: 图片已设置到label")

                # 更新信息栏
                file_size = os.path.getsize(filepath) / 1024  # KB
                info_label.configure(
                    text=f"[{index+1}/{len(viewer_state['screenshots'])}] "
                         f"{os.path.basename(filepath)} | "
                         f"{original_size[0]}x{original_size[1]} | {file_size:.1f} KB",
                    foreground="black"
                )
                viewer_state['current_index'] = index

            except Exception as e:
                error_msg = f"加载失败: {e}"
                info_label.configure(text=error_msg, foreground="red")
                self.log(f"截图查看器: {error_msg}")
                import traceback
                self.log(f"错误详情: {traceback.format_exc()}")

        def create_thumbnail(filepath, index):
            """创建缩略图按钮"""
            if not os.path.exists(filepath):
                return

            try:
                img = Image.open(filepath)
                # 兼容不同版本的Pillow
                try:
                    img.thumbnail((200, 150), Image.Resampling.LANCZOS)
                except AttributeError:
                    img.thumbnail((200, 150), Image.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                viewer_state['thumb_images'].append(photo)

                # 缩略图容器
                thumb_container = ttk.Frame(thumb_frame, relief=tk.RAISED, borderwidth=1)
                thumb_container.pack(fill=tk.X, padx=5, pady=5)

                # 图片按钮
                btn = tk.Button(thumb_container, image=photo, cursor="hand2",
                              command=lambda idx=index: load_and_show_image(idx))
                btn.pack()

                # 文件名标签
                filename = os.path.basename(filepath)
                ttk.Label(thumb_container, text=filename[:25],
                         font=("Arial", 8), foreground="gray").pack()

            except Exception as e:
                print(f"缩略图加载失败: {e}")

        def delete_current():
            """删除当前预览的截图"""
            if not viewer_state['screenshots']:
                return

            idx = viewer_state['current_index']
            filepath = viewer_state['screenshots'][idx]

            # 确认对话框
            from tkinter import messagebox
            if not messagebox.askyesno("确认删除",
                                      f"确定要删除这张截图吗？\n{os.path.basename(filepath)}"):
                return

            try:
                # 删除文件
                if os.path.exists(filepath):
                    os.remove(filepath)

                # 从列表中移除
                viewer_state['screenshots'].pop(idx)

                # 如果列表为空，关闭窗口
                if not viewer_state['screenshots']:
                    viewer.destroy()
                    return

                # 刷新界面
                refresh_viewer()

                # 显示相邻的图片
                new_idx = min(idx, len(viewer_state['screenshots']) - 1)
                load_and_show_image(new_idx)

            except Exception as e:
                info_label.configure(text=f"删除失败: {e}", foreground="red")

        def refresh_viewer():
            """刷新缩略图列表"""
            # 清空缩略图
            for widget in thumb_frame.winfo_children():
                widget.destroy()
            viewer_state['thumb_images'].clear()

            # 重新加载
            for i, filepath in enumerate(viewer_state['screenshots']):
                create_thumbnail(filepath, i)

            # 更新滚动区域
            thumb_frame.update_idletasks()
            thumb_canvas.configure(scrollregion=thumb_canvas.bbox("all"))

            # 更新标题
            viewer.title(f"截图管理器 - 共 {len(viewer_state['screenshots'])} 张")

        # 控制按钮
        ttk.Button(control_frame, text="❌ 删除当前",
                  command=delete_current).pack(side=tk.RIGHT, padx=5)
        ttk.Button(control_frame, text="🔄 刷新",
                  command=refresh_viewer).pack(side=tk.RIGHT, padx=5)
        ttk.Button(control_frame, text="📁 打开文件夹",
                  command=lambda: os.startfile(os.path.dirname(screenshots[0]))).pack(side=tk.RIGHT, padx=5)

        # 初始化：加载所有缩略图
        for i, filepath in enumerate(screenshots):
            create_thumbnail(filepath, i)

        # 更新滚动区域
        thumb_frame.update_idletasks()
        thumb_canvas.configure(scrollregion=thumb_canvas.bbox("all"))

        # 默认显示第一张
        if screenshots:
            load_and_show_image(0)

        # 焦点恢复
        viewer.protocol("WM_DELETE_WINDOW", viewer.destroy)
        viewer.transient(self.root)
        viewer.focus_force()

    # ========== 系统托盘功能 ==========
    def create_tray_icon(self):
        """创建托盘图标"""
        try:
            icon_path = os.path.join(SCRIPT_DIR, 'cctv.ico')
            if os.path.exists(icon_path):
                return Image.open(icon_path)
            else:
                self.log("托盘图标 cctv.ico 未找到。")
        except Exception as e:
            self.log(f"加载托盘图标 cctv.ico 失败: {e}")

        # 如果加载失败，回退到原来的动态创建图标
        self.log("回退到动态创建默认托盘图标。")
        width = 64
        height = 64
        image = Image.new('RGB', (width, height), color=(0, 176, 240))
        dc = ImageDraw.Draw(image)
        dc.ellipse([2, 2, width-2, height-2], fill=(0, 176, 240), outline='white', width=3)
        dc.text((width//2, height//2), "S", fill='white', anchor="mm")
        return image

    def init_tray(self):
        """初始化系统托盘"""
        try:
            icon_image = self.create_tray_icon()

            # 创建托盘菜单
            menu = (
                item('显示窗口', self.show_window, default=True),
                item('隐藏窗口', self.hide_window),
                item('启动监控', self.start_monitoring_from_tray, visible=lambda item: not self.is_running),
                item('停止监控', self.stop_monitoring_from_tray, visible=lambda item: self.is_running),
                item('退出程序', self.quit_app)
            )

            self.tray_icon = pystray.Icon("SecurityMonitor", icon_image, "安全监控系统", menu)

            # 在单独线程中运行托盘图标
            Thread(target=self._run_tray, daemon=True).start()

        except Exception as e:
            self.log(f"托盘图标初始化失败: {e}")

    def _run_tray(self):
        """在后台线程运行托盘"""
        try:
            self.tray_running = True
            self.tray_icon.run()
        except Exception as e:
            self.log(f"托盘运行错误: {e}")

    def show_window(self, icon=None, item=None):
        """显示主窗口"""
        self.root.after(0, self._show_window)

    def _show_window(self):
        """实际显示窗口的方法（在主线程中执行）"""
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide_window(self, icon=None, item=None):
        """隐藏主窗口到托盘"""
        self.root.after(0, self._hide_window)

    def _hide_window(self):
        """实际隐藏窗口的方法（在主线程中执行）"""
        self.root.withdraw()

    def start_monitoring_from_tray(self, icon=None, item=None):
        """从托盘启动监控"""
        self.root.after(0, self.start_monitoring)

    def stop_monitoring_from_tray(self, icon=None, item=None):
        """从托盘停止监控"""
        self.root.after(0, self.stop_monitoring)

    def quit_app(self, icon=None, item=None):
        """完全退出程序"""
        self.root.after(0, self._quit_app)

    def _quit_app(self):
        """实际退出程序的方法"""
        # 停止托盘
        if self.tray_icon:
            self.tray_icon.stop()
        # 保存参数和窗口布局
        self.save_config()
        self.save_window_layout()
        # 停止监控
        if self.is_running:
            self.stop_monitoring()
        # 关闭窗口
        self.root.destroy()

    # ========== 报警弹窗提示 ==========
    def show_alert_popup(self, frames):
        """在屏幕右下角显示报警弹窗（参考security_monitor.py样式）"""
        try:
            # 创建弹窗
            popup = tk.Toplevel(self.root)

            # 先隐藏窗口，设置完成后再显示
            popup.withdraw()

            # UI 配色与样式设置
            bg_color = "#202020"       # 深灰色背景
            text_color = "#E0E0E0"     # 浅灰白色文字
            accent_color = "#FF4500"   # 警示橙红色
            font_title = ("Microsoft YaHei UI", 14, "bold")  # 调大字体
            font_body = ("Microsoft YaHei UI", 11)           # 调大字体

            # 无边框与置顶设置
            popup.overrideredirect(True)
            popup.attributes('-topmost', True)
            popup.attributes('-alpha', 0.95)
            popup.configure(bg=bg_color)

            # 布局设计 - 左侧警示条
            bar = tk.Frame(popup, bg=accent_color, width=6)
            bar.pack(side="left", fill="y")

            # 内容容器
            content_frame = tk.Frame(popup, bg=bg_color, padx=15)
            content_frame.pack(side="left", fill="both", expand=True)

            # 标题与内容
            lbl_title = tk.Label(content_frame, text="⚠️ Warning",
                                 font=font_title, bg=bg_color, fg=accent_color, anchor="w")
            lbl_title.pack(fill="x", pady=(15, 2))

            timestamp = datetime.datetime.now().strftime('%H:%M:%S')
            lbl_msg = tk.Label(content_frame, text=f"Motion detected at {timestamp}",
                               font=font_body, bg=bg_color, fg=text_color, anchor="w")
            lbl_msg.pack(fill="x")

            # 更新窗口以获取正确的尺寸
            popup.update_idletasks()

            # 窗口尺寸与位置计算
            window_width = 320
            window_height = 100  # 因为字体变大，稍微增加高度
            padding_right = 10
            padding_bottom = 80  # 避开底部任务栏

            # 多屏幕环境下，在主窗口所在屏幕的右下角显示弹窗
            # 获取主窗口的位置和尺寸
            main_x = self.root.winfo_x()
            main_y = self.root.winfo_y()
            main_width = self.root.winfo_width()
            main_height = self.root.winfo_height()

            # 使用Windows API获取准确的显示器信息
            try:
                import win32api
                import win32con

                # 获取所有显示器信息
                monitors = win32api.EnumDisplayMonitors()

                # 找到主窗口所在的显示器
                window_center_x = main_x + main_width // 2
                window_center_y = main_y + main_height // 2

                target_monitor = None
                for monitor in monitors:
                    monitor_info = win32api.GetMonitorInfo(monitor[0])
                    monitor_rect = monitor_info['Monitor']  # (left, top, right, bottom)
                    left, top, right, bottom = monitor_rect

                    # 检查窗口中心点是否在这个显示器内
                    if left <= window_center_x < right and top <= window_center_y < bottom:
                        target_monitor = monitor_rect
                        break

                if target_monitor:
                    # 使用找到的显示器边界
                    screen_right = target_monitor[2]  # right
                    screen_bottom = target_monitor[3]  # bottom
                    x_pos = screen_right - window_width - padding_right
                    y_pos = screen_bottom - window_height - padding_bottom
                else:
                    # 降级方案
                    raise Exception("未找到显示器")

            except:
                # 如果win32api不可用，使用简化计算
                # 假设所有屏幕的总宽度，放在最右边
                screen_width = popup.winfo_screenwidth()
                screen_height = popup.winfo_screenheight()
                x_pos = screen_width - window_width - padding_right
                y_pos = screen_height - window_height - padding_bottom

            # 设置窗口大小和位置
            popup.geometry(f"{window_width}x{window_height}+{x_pos}+{y_pos}")

            # 更新并显示窗口
            popup.update_idletasks()
            popup.deiconify()  # 显示窗口

            # 点击任意位置关闭
            def dismiss(event=None):
                try:
                    popup.destroy()
                except:
                    pass

            # 绑定点击事件
            for widget in [popup, bar, content_frame, lbl_title, lbl_msg]:
                widget.bind("<Button-1>", dismiss)

            # 3.5秒后自动消失
            popup.after(3500, dismiss)

        except Exception as e:
            self.log(f"弹窗显示失败: {e}")

    def on_close(self):
        """窗口关闭时隐藏到托盘而不是退出"""
        # 保存参数和窗口布局
        self.save_config()
        self.save_window_layout()
        # 隐藏到托盘
        self._hide_window()
        self.log("程序已最小化到系统托盘，参数已保存。")

    def _populate_presets_combo(self):
        """用配置中的预设填充下拉菜单"""
        presets = list(self.config.get("custom_presets", {}).keys())
        
        # 确保下拉菜单存在
        if not hasattr(self, 'preset_combo'):
            return
            
        if not presets:
            presets = ["无自定义预设"]
            self.preset_combo.set(presets[0])
            if hasattr(self, 'btn_load_preset'): self.btn_load_preset.configure(state="disabled")
            if hasattr(self, 'btn_delete_preset'): self.btn_delete_preset.configure(state="disabled")
        else:
            if hasattr(self, 'btn_load_preset'): self.btn_load_preset.configure(state="normal")
            if hasattr(self, 'btn_delete_preset'): self.btn_delete_preset.configure(state="normal")

        self.preset_combo.configure(values=presets)
        if self.preset_combo.get() not in presets:
            self.preset_combo.set(presets[0])

    def _load_preset(self):
        """加载选定的预设"""
        preset_name = self.preset_combo.get()
        presets = self.config.get("custom_presets", {})
        if preset_name in presets:
            preset_data = presets[preset_name]
            
            # 定义可设置的参数键
            preset_keys = [
                "min_area", "continuous_frames", "threshold", 
                "alert_cooldown", "loop_delay"
            ]
            
            for key in preset_keys:
                if key in preset_data:
                    self.config[key] = preset_data[key]

            # 更新UI滑块
            self.scale_sensitivity.set(self.config['min_area'])
            self.on_sensitivity_change(self.config['min_area']) # 触发更新
            
            self.scale_frames.set(self.config['continuous_frames'])
            self.on_frames_change(self.config['continuous_frames'])

            self.scale_threshold.set(self.config['threshold'])
            self.on_threshold_change(self.config['threshold'])
            
            self.scale_cooldown.set(self.config['alert_cooldown'])
            self.on_cooldown_change(self.config['alert_cooldown'])
            
            target_fps = int(1.0 / self.config['loop_delay']) if self.config['loop_delay'] > 0 else 5
            self.scale_target_fps.set(target_fps)
            self.on_target_fps_change(target_fps)

            self.log(f"已加载预设: {preset_name}")
        else:
            self.log(f"预设 '{preset_name}' 不存在", "warning")

    def _save_preset(self):
        """保存当前设置为新预设"""
        dialog = ctk.CTkInputDialog(text="请输入预设名称:", title="保存预设")
        preset_name = dialog.get_input()

        if preset_name and preset_name.strip():
            preset_name = preset_name.strip()
            # 检查名称是否已存在
            if preset_name in self.config.get("custom_presets", {}):
                if not messagebox.askyesno("覆盖预设", f"预设 '{preset_name}' 已存在。\n是否要覆盖它？"):
                    self.log("保存操作已取消。")
                    return

            # 保存当前参数
            current_preset = {
                "min_area": self.config['min_area'],
                "continuous_frames": self.config['continuous_frames'],
                "threshold": self.config['threshold'],
                "alert_cooldown": self.config['alert_cooldown'],
                "loop_delay": self.config['loop_delay']
            }
            
            if "custom_presets" not in self.config:
                self.config["custom_presets"] = {}
                
            self.config["custom_presets"][preset_name] = current_preset
            self.save_config() # 立即保存
            self.log(f"预设 '{preset_name}' 已保存。")
            
            # 刷新下拉菜单
            self._populate_presets_combo()
            self.preset_combo.set(preset_name)
        else:
            self.log("预设名称不能为空，保存失败。")

    def _delete_preset(self):
        """删除选定的预设"""
        preset_name = self.preset_combo.get()
        presets = self.config.get("custom_presets", {})

        if preset_name in presets and preset_name != "无自定义预设":
            if messagebox.askyesno("删除预设", f"确定要删除预设 '{preset_name}' 吗？"):
                del self.config["custom_presets"][preset_name]
                self.save_config()
                self.log(f"预设 '{preset_name}' 已删除。")
                self._populate_presets_combo()
        else:
            self.log(f"无法删除：预设 '{preset_name}' 不存在或无效。", "warning")



if __name__ == "__main__":
    root = ctk.CTk()
    app = SecurityApp(root)
    root.mainloop()