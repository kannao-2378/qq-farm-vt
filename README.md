# QQ 农场控制台（qq-farm-vt）

Windows 下图形控制台：游戏窗口识别、任务控制、种植策略参考。仅供学习与交流，请遵守游戏服务条款。

## 环境

- Windows 10/11  
- Python 3.10+（建议 3.11）

## 安装依赖

在项目根目录执行：

```bash
py -3 -m pip install -r requirements.txt
```

没有 `py` 时用：`python -m pip install -r requirements.txt`

## 启动

双击 **`启动.bat`**，或在项目根执行：

```bash
python gui_scripts/new_main_pyqt.py
```

## 数据位置

- **`user_data/`**：本地状态（含打赏计数、界面主题等）  
- **`logs/`**：运行日志  
- **`assets/donation_qr.png`**：自愿打赏弹窗展示的收款码，**请保留在仓库中**（与程序一并分发）。  
- **`assets/yinyong/`**：游戏窗口识别与点击用的模板 PNG（由程序读取）；`assets/cs/` 为未接入脚本的素材备份，可忽略  

整夹拷贝可换机；重置可删除 `user_data` 内对应文件。

清除运行产生的日志、调试图、统计库、操作会话目录：双击 **`scripts/清理运行痕迹.bat`**，或在项目根执行 `py -3 scripts/clean_runtime_artifacts.py`（不删 `user_data` 与 `gui_scripts` 里的 JSON 配置）。

### 上传 GitHub 前建议

- 已清空 `user_data/`（仅保留 `.gitkeep`），`gui_scripts/config.json` 与 `planting_strategy_config.json` 已恢复为默认占位；克隆后需在程序里重新框选游戏窗口。  
- 模板图在 `assets/yinyong/`，勿提交含隐私的截图；`assets/cs/` 仅为本地备份素材。

## 打赏提示（自愿）

弹窗与计数规则由程序按本地 `user_data/donation_state.json` 执行；删除该文件可重置。是否支付由你自行决定，程序不验证。

- 默认**第 6 次及以后启动**才可能弹出（前 5 次仅累计启动次数）。  
- 累计点「已赏」达到 3 次后不再定时弹出；点「未赏」前几次会退出程序（次数见 `donation_dialog.py` 常量）。  
- 再次弹出间隔由「已赏」时的记录时间决定（默认约 24 小时，见 `REMINDER_SEC`）。

## 根目录文件

| 文件 | 用途 |
|------|------|
| `启动.bat` | 启动程序 |
| `requirements.txt` | 依赖列表 |
| `README.md` | 本说明 |

主程序与资源分别在 `gui_scripts/`、`assets/`、`seed_calc/` 等子目录中。
