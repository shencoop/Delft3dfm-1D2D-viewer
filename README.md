# Delft3D-FM 1D2D 多分區水理成果展示圖台與轉檔系統

本專案為專注於 **Delft3D-FM 多分區水理成果 WebGIS 展示** 與 **模式輸出 NetCDF (map.nc / fou.nc) 自動轉換為 Zarr / COG GeoTIFF** 的獨立精簡套件。

---

## 🚀 快速開始

### 1. 安裝 Pixi 包管理工具 (僅需執行一次)
```powershell
iwr -useb https://pixi.sh/install.ps1 | iex
```

### 2. 安裝環境與相依性
```powershell
pixi install
```

### 3. 一鍵啟動展示圖台
```powershell
pixi run viewer
```
* 瀏覽器自動開啟圖台網址：`http://127.0.0.1:8088/`

---

## 🛠️ Delft3D-FM 轉檔工具

將 Delft3D-FM 模式輸出資料夾中的所有分區 `*_map.nc` 與 `*_fou.nc` 批次轉換為 Zarr 與 COG GeoTIFF：

```powershell
# 語法: pixi run convert -i <輸入NC目錄> -o <輸出目錄>
pixi run convert -i "D:\2026WRAP\ZARR\0005\Changhua-12hr-300mm-Yuanlin_NC" -o "D:\2026WRAP\ZARR\0005\Changhua-12hr-300mm-Yuanlin_ZARR"
```

---

## 📖 詳細說明手冊
請參閱 [docs/USER_MANUAL.md](docs/USER_MANUAL.md) 獲取完整安裝指引、操作說明與語法範例。

## 📄 授權條款
本專案採用 [MIT License](LICENSE) 授權。
