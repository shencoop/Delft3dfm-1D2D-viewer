# Delft3D-FM 1D2D 多分區水理成果展示圖台與轉檔系統使用者手冊

本手冊專為**完全未預裝 Python 或 Conda 環境之全新使用者**所編撰。系統採用現代化包管理工具 **`Pixi`**，具備「零環境污染、全自動相依性下載、單一指令啟動」之特性。

---

## 目錄
1. [環境建置與系統安裝 (無 Python 初始環境)](#1-環境建置與系統安裝-無-python-初始環境)
2. [系統快速啟動 (One-Click Launch)](#2-系統快速啟動-one-click-launch)
3. [Delft3D-FM 成果轉檔工具 (NC to Zarr & COG)](#3-delft3d-fm-成果轉檔工具-nc-to-zarr--cog)
4. [WebGIS 成果展示圖台核心功能與操作](#4-webgis-成果展示圖台核心功能與操作)
5. [淹水深度六階標準色彩與手冊規範](#5-淹水深度六階標準色彩與手冊規範)
6. [常見問題與故障排除 (FAQ)](#6-常見問題與故障排除-faq)

---

## 1. 環境建置與系統安裝 (無 Python 初始環境)

本專案採用 **Pixi** 作為獨立環境封裝引擎。使用者電腦**無須手動安裝 Python、GDAL、C++ 編譯器或設定系統 PATH**，Pixi 會全自動在專案目錄下建構隔離之執行環境。

### 步驟 1.1：安裝 Pixi 包管理工具 (僅需執行一次)

請開啟 Windows 的 **PowerShell** (按 `Win + X` 選擇「Windows PowerShell」或「終端機」)，複製並貼上以下官方安裝指令後按 Enter：

```powershell
iwr -useb https://pixi.sh/install.ps1 | iex
```

> **提示**：安裝完成後，若提示找不到 `pixi` 指令，請關閉 PowerShell 視窗並**重新開啟一個新的 PowerShell 視窗**即可。

---

### 步驟 1.2：進入專案目錄並自動建置環境

在 PowerShell 視窗中，切換至本專案目錄：

```powershell
cd d:\2026code
```

執行環境初始化指令（Pixi 將自動下載獨立的 Python 3.12、GDAL、Rasterio、FastAPI、Xarray、Zarr 等所有函式庫）：

```powershell
pixi install
```

> **說明**：下載與建置過程約需 1~2 分鐘。完成後即具備完整的 Delft3D-FM 轉檔與 WebGIS 展示服務能力！

---

## 2. 系統快速啟動 (One-Click Launch)

在專案目錄 `d:\2026code` 下，直接執行專案任務指令：

```powershell
pixi run dfm-viewer
```

### 啟動特性說明：
1. **智慧連接埠衝突自動避讓**：系統預設使用 `8088`，若偵測到埠號已被其他程式占用，將**自動遞增切換至可行之連接埠（如 `8089`、`8090`...）**，杜絕 WinError 10048 衝突中斷。
2. **自動開啟圖台瀏覽器**：服務啟動後，將自動呼叫 Windows 預設瀏覽器開啟展示圖台：
   👉 **`http://127.0.0.1:8088/dfm_viewer.html`**

---

## 3. Delft3D-FM 成果轉檔工具 (NC to Zarr & COG)

若使用者已有 Delft3D-FM 模式輸出之 `*_map.nc`（時序網格）與 `*_fou.nc`（最大淹水深度），可使用內建轉檔工具自動批次轉換為適合 Web 瀏覽之 Zarr 與 COG GeoTIFF。

### 3.1 CLI 轉檔指令語法與參數說明

#### 完整語法結構：
```powershell
pixi run dfm-convert -i <Delft3D-FM輸入目錄> [-o <輸出目錄>] [--crs <坐標系統代碼>]
```

#### 參數詳細說明表：
| 參數名稱 | 縮寫 | 必填 | 預設值 | 說明 |
| :--- | :---: | :---: | :---: | :--- |
| `--input-dir` | `-i` | **是** | 無 | 包含 Delft3D-FM 模式輸出檔案（`*_map.nc` / `*_fou.nc`）的資料夾路徑。支援多層目錄自動遞迴搜尋。 |
| `--output-dir` | `-o` | 否 | 輸入目錄 | 轉換後 Zarr 資料夾、COG GeoTIFF 與索引檔儲存之目標路徑。若未指定則直接輸出至輸入目錄。 |
| `--crs` | 無 | 否 | `EPSG:3826` | 輸入與輸出圖資之投影坐標系代碼（預設為臺灣常用之 TWD97 / 121 分帶二度分帶坐標 EPSG:3826）。 |

---

### 3.2 常見情境語法範例

#### 範例 1：基本批次轉檔（指定輸入與輸出目錄）
將 `D:\2026WRAP\ZARR\0005\Changhua-12hr-300mm-Yuanlin_NC` 目錄下的 11 個分區檔案批次轉換至專屬輸出資料夾：
```powershell
pixi run dfm-convert -i "D:\2026WRAP\ZARR\0005\Changhua-12hr-300mm-Yuanlin_NC" -o "D:\2026WRAP\ZARR\0005\Changhua-12hr-300mm-Yuanlin_ZARR"
```

#### 範例 2：原目錄直接轉換（輸出在原資料夾）
若省略 `-o` 參數，轉換完成的 `.zarr` 與 `_cog.tif` 會直接產生在原 NC 資料夾內：
```powershell
pixi run dfm-convert -i "D:\Simulation_Output\Scenario_01"
```

#### 範例 3：指定不同坐標系（例如澎湖/金門 TWD97 119分帶 EPSG:3825 或 WGS84 Web Mercator EPSG:3857）
```powershell
pixi run dfm-convert -i "D:\Data\Penghu_DFM_NC" -o "D:\Data\Penghu_Zarr" --crs "EPSG:3825"
```

---

### 3.3 Python API 程式庫調用範例

除了 CLI 指令外，亦可在自訂 Python 腳本或 Jupyter Notebook 中調用本模組進行客製化轉檔：

```python
import sys
sys.path.insert(0, r"d:\2026code\floodgpu\src")

from floodgpu.convert_dfm_output import (
    process_dfm_directory_pipeline,
    convert_map_nc_to_zarr,
    convert_max_depth_to_cog
)

# 1. 全自動批次轉檔
summary = process_dfm_directory_pipeline(
    input_dir=r"D:\2026WRAP\ZARR\0005\Changhua-12hr-300mm-Yuanlin_NC",
    output_dir=r"D:\2026code\scratch\converted_output",
    crs_code="EPSG:3826"
)
print("轉檔完成，分區清單:", list(summary.keys()))

# 2. 單一分區單獨轉換範例
# 轉換時序 map.nc -> zarr
convert_map_nc_to_zarr(
    nc_path=r"D:\2026WRAP\ZARR\0005\Changhua-12hr-300mm-Yuanlin_NC\Changhua_Yuanlin_FlowFM_0000_map.nc",
    output_zarr_path=r"d:\2026code\scratch\0000_map.zarr",
    var_name="Mesh2d_waterdepth",
    res=5.0  # 5m 結構化網格解析度
)

# 轉換最大淹水深度 fou.nc -> COG GeoTIFF (含 4 階金字塔)
convert_max_depth_to_cog(
    input_nc_path=r"D:\2026WRAP\ZARR\0005\Changhua-12hr-300mm-Yuanlin_NC\Changhua_Yuanlin_FlowFM_0000_fou.nc",
    output_tif_path=r"d:\2026code\scratch\0000_max_cog.tif",
    is_fou=True,
    crs_code="EPSG:3826",
    res=5.0
)
```

---

### 3.4 轉檔核心產出與結構說明：
1. **時序 Zarr 分塊檔 (`*_map.zarr`)**：
   - 維度結構：`(time, y, x)`，例如 `(13, 554, 457)`。
   - 變數名稱：`Mesh2d_waterdepth`（水深，單位公尺）。
   - 啟用 Consolidated Metadata，提供毫秒級分塊遠端檢索。
2. **最大淹水深度 COG (`*_fou_cog.tif` / `*_max_depth_cog.tif`)**：
   - 格式：Cloud Optimized GeoTIFF，內建 Deflate 壓縮與 Tiled (256x256) 分塊。
   - 金字塔層級：標準 **4 階空間金字塔 (Overviews: 2, 4, 8, 16)**，Nearest 取樣。
3. **全區索引檔 (`partitions_metadata.json`)**：
   - 自動匯整 11 個分區之相對應 Zarr 與 COG 路徑映射，供圖台後端 API 瞬時載入。

---

## 4. WebGIS 成果展示圖台核心功能與操作

```mermaid
flowchart LR
    A[📁 資料來源選擇] --> B[🗺️ WMTS 底圖切換]
    B --> C[🧩 11 分區邊界套疊]
    C --> D[⏱️ MM-DD HH:mm 時序播放]
    D --> E[📊 2.5m 精度點位水深歷線]
```

### 功能 1：📁 ZARR / COG 資料來源自由切換
* **預設載入**：`D:\2026WRAP\ZARR\0005\Changhua-12hr-300mm-Yuanlin_ZARR`（共 11 個分區）。
* **自由更換路徑**：在側邊欄輸入自訂路徑，或點擊「**📂 點選瀏覽資料夾**」按鈕，點擊「🔄 重新掃描」即可無縫切換其他場次成果。

### 功能 2：🗺️ WMTS 多來源底圖即時切換
* **臺灣通用電子地圖 (EMAP)**：清晰展示道路、街廓、河川與行政區界。
* **臺灣正射影像圖 (PHOTO)**：高解析度空照正射影像，利於實體地貌比對。
* **CartoDB 暗黑風格 (Dark)**：高對比科技暗黑底圖，突顯水深色階分佈。
* **OpenStreetMap (OSM)**：國際通用開源圖資。

### 功能 3：🧩 多分區邊界管理與自訂向量套疊
* **分區獨立控制**：側邊欄清單可個別勾選/取消 11 個分區之水深圖層或外框虛線（Bounding Box）。
* **向量檔案套疊**：支援點擊「選擇檔案」上傳使用者的 **GeoJSON** 向量圖層（如 1D 河道中心線、抽水站、村里邊界）。

### 功能 4：⏱️ 時間序列動態播放
* **時間顯示格式**：採用 **`MM-DD HH:mm`**（例如：`01-01 00:00` 至 `01-13 00:00`），不冗餘顯示年份。
* **動態播放控制**：提供 **▶ 播放 / ⏸ 暫停** 按鈕與時間滑桿，以流暢幀率動態呈現淹水擴散演變。

### 功能 5：📊 點位水深時序查詢 (2.5m 精度 & 多圖層最大值包絡)
* **2.5m 物理網格定位**：點擊地圖任意位置，系統自動在 5m 物理網格中搜尋最近鄰點（誤差 $\le 2.5\text{m}$）。
* **多圖層最大值包絡 (Max Envelope)**：若點擊位置落在多個重疊分區交界，系統自動逐時步取最大值（$\max(h)$），彈出水深氣泡標籤，並於右下角繪製包含全區合成最大水深與各分區對比歷線之折線圖。

---

## 5. 淹水深度六階標準色彩與手冊規範

系統嚴格遵循經濟部水利署《淹水潛勢圖製作手冊》與水理模擬規範，預設色彩如下：

| 水深級距 | 色彩名稱 | RGB 顏色 | 預設透明度 | 手冊展示規範 |
| :---: | :---: | :---: | :---: | :---: |
| **0.1m ~ 0.3m** | 淺藍色 | `RGB(198, 219, 239)` | **70%** | **預設隱藏** (可手動勾選開啟) |
| **0.3m ~ 0.5m** | 淺藍色 | `RGB(198, 219, 239)` | **40%** | 淺層積淹水 (預設展示) |
| **0.5m ~ 1.0m** | 中淺藍色 | `RGB(120, 180, 214)` | **40%** | 中度淹水 |
| **1.0m ~ 2.0m** | 中藍色 | `RGB(66, 146, 198)` | **40%** | 深度淹水 |
| **2.0m ~ 3.0m** | 中深藍色 | `RGB(37, 81, 156)` | **40%** | 重度淹水 |
| **> 3.0m** | 深藍色 | `RGB(8, 48, 107)` | **40%** | 極深水理淹水 (標準深藍色) |

### 色彩與透明度自訂功能：
1. **0.1m ~ 0.3m 淺積水開關**：側邊欄提供 `☑ 顯示 0.1m ~ 0.3m 淺積水` 核取方塊，勾選後圖台與圖例將同步展開淺水層。
2. **整體透明度滑桿**：支援 `10% ~ 150%` 動態調節，自訂圖層穿透感。
3. **配色方案切換**：支援切換「標準水利六階藍色系」與「藍-黃-紅 災害警示系」。

---

## 6. 常見問題與故障排除 (FAQ)

### Q1：點擊地圖時沒有跳出水深圖表？
* **解答**：請確認點選區域是否具有淹水顏色。若點選乾燥陸域（水深為 0m），地圖標記會提示「該點位無水深資料」；點選著色區域即可立即彈出歷線圖表。

### Q2：執行 `pixi run dfm-viewer` 時提示連線被拒絕？
* **解答**：請確認終端機視窗未被關閉。若先前有舊程序執行中，請在終端機按 `Ctrl + C` 結束後重新執行 `pixi run dfm-viewer`。

### Q3：如何更換預設載入的 Zarr 目錄？
* **解答**：直接於側邊欄「📁 ZARR / COG 資料來源」文字框中輸入新目錄之絕對路徑（例如：`D:\MyProject\Sim_Results`），點擊「🔄 重新掃描」即可立即載入。
