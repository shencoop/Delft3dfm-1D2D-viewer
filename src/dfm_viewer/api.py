"""Delft3D-FM & FloodGPU Multi-Partition Spatio-Temporal Viewer Engine.
Supports dynamic Zarr/COG scanning, multi-partition overlay, timeseries point querying, and WMTS base layers.
"""
from pathlib import Path
from dataclasses import dataclass, field
import os, glob, io, json
import numpy as np
import pandas as pd
import xarray as xr
from pyproj import CRS, Transformer
from rasterio.transform import Affine, from_bounds, array_bounds
from rasterio.warp import reproject, Resampling, transform_bounds
from PIL import Image
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Delft3D-FM Multi-Partition Spatio-Temporal Viewer", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

WEB_DIR = Path(__file__).parent / "web"

@dataclass
class PartitionInfo:
    id: str
    name: str
    path: str
    crs: str               # e.g. 'EPSG:3826', 'EPSG:3825', 'EPSG:4326'
    bounds_native: list    # [xmin, ymin, xmax, ymax] in native CRS
    bounds_wgs84: list     # [w, s, e, n] in EPSG:4326
    shape: list            # [ny, nx]
    transform: list        # Affine elements
    times: list            # float or iso strings
    var_name: str          # e.g. 'Mesh2d_waterdepth' or 'h'

@dataclass
class DataCatalog:
    current_path: str = r"D:\2026WRAP\ZARR\0005\Changhua-12hr-300mm-Yuanlin_ZARR"
    partitions: dict[str, PartitionInfo] = field(default_factory=dict)
    union_bounds_3826: list = field(default_factory=lambda: [0, 0, 0, 0])
    union_bounds_wgs84: list = field(default_factory=lambda: [0, 0, 0, 0])
    times: list = field(default_factory=list)
    time_labels: list = field(default_factory=list)

catalog = DataCatalog()

def scan_directory(target_path: str):
    p = Path(target_path).resolve()
    if not p.exists():
        raise ValueError(f"路徑不存在: {target_path}")
    
    zarr_files = sorted(glob.glob(str(p / "*.zarr")))
    if not zarr_files and p.name.endswith(".zarr"):
        zarr_files = [str(p)]
    
    if not zarr_files:
        # Check subdirectories
        zarr_files = sorted(glob.glob(str(p / "**" / "*.zarr"), recursive=True))

    if not zarr_files:
        raise ValueError(f"在 {target_path} 中未找到任何 ZARR 分區成果")

    parts = {}
    all_xmin, all_ymin = float("inf"), float("inf")
    all_xmax, all_ymax = float("-inf"), float("-inf")
    all_w, all_s = float("inf"), float("inf")
    all_e, all_n = float("-inf"), float("-inf")
    global_times = []
    global_time_labels = []

    for i, zf in enumerate(zarr_files):
        pid = f"part_{i:03d}"
        pname = Path(zf).name
        try:
            ds = xr.open_zarr(zf, consolidated=False)
            var = "Mesh2d_waterdepth" if "Mesh2d_waterdepth" in ds else ("h" if "h" in ds else list(ds.data_vars.keys())[0])
            
            # 動態取得坐標系 (預設 EPSG:3826，支援 EPSG:3825 與 EPSG:4326)
            native_crs = ds.attrs.get("crs", ds.attrs.get("spatial_ref", "EPSG:3826")).upper()
            
            x_vals = ds.x.values
            y_vals = ds.y.values
            xmin, xmax = float(np.nanmin(x_vals)), float(np.nanmax(x_vals))
            ymin, ymax = float(np.nanmin(y_vals)), float(np.nanmax(y_vals))
            
            # 若坐標範圍在經緯度範圍內，強制修正為 EPSG:4326
            if native_crs in ["EPSG:3826", "EPSG:3825"] and (xmax <= 180.0 and xmin >= -180.0 and ymax <= 90.0 and ymin >= -90.0):
                native_crs = "EPSG:4326"
            
            dx = float(abs(x_vals[1] - x_vals[0])) if len(x_vals) > 1 else (0.00005 if native_crs == "EPSG:4326" else 5.0)
            dy = float(abs(y_vals[1] - y_vals[0])) if len(y_vals) > 1 else (0.00005 if native_crs == "EPSG:4326" else 5.0)
            
            # 像素邊界與 Affine Transform
            top_y = y_vals[0] if y_vals[0] > y_vals[-1] else y_vals[-1]
            left_x = x_vals[0] if x_vals[0] < x_vals[-1] else x_vals[-1]
            y_sign = -dy if y_vals[0] > y_vals[-1] else dy
            x_sign = dx if x_vals[0] < x_vals[-1] else -dx
            
            c = left_x - dx / 2.0
            f = top_y + dy / 2.0
            tf = Affine(x_sign, 0.0, c, 0.0, y_sign, f)
            
            # 精確像素邊界範圍 (Outer Bounding Box)
            bbox_xmin = xmin - dx / 2.0
            bbox_ymin = ymin - dy / 2.0
            bbox_xmax = xmax + dx / 2.0
            bbox_ymax = ymax + dy / 2.0
            
            # 使用 densified transform_bounds 確保投影幾何無失真 (支援 3826/3825/4326 -> 4326)
            if native_crs == "EPSG:4326":
                bw, bs, be, bn = bbox_xmin, bbox_ymin, bbox_xmax, bbox_ymax
            else:
                bw, bs, be, bn = transform_bounds(native_crs, "EPSG:4326", bbox_xmin, bbox_ymin, bbox_xmax, bbox_ymax, densify_pts=21)
            
            all_xmin = min(all_xmin, bbox_xmin)
            all_ymin = min(all_ymin, bbox_ymin)
            all_xmax = max(all_xmax, bbox_xmax)
            all_ymax = max(all_ymax, bbox_ymax)
            
            all_w = min(all_w, bw)
            all_s = min(all_s, bs)
            all_e = max(all_e, be)
            all_n = max(all_n, bn)
            all_e = max(all_e, be)
            all_n = max(all_n, bn)
            
            # 時間序列解析邏輯 (格式: MM-DD HH:mm，不顯示年份)
            t_raw = ds.time.values
            t_vals = []
            t_lbls = []
            
            is_datetime = np.issubdtype(ds.time.dtype, np.datetime64)
            if is_datetime:
                ts_series = [pd.to_datetime(t) for t in t_raw]
                for dt in ts_series:
                    t_vals.append(dt.timestamp())
                    t_lbls.append(dt.strftime("%m-%d %H:%M"))
            else:
                for j, t in enumerate(t_raw):
                    v = float(t)
                    t_vals.append(v)
                    t_lbls.append(f"Step {j:02d}")

            if len(t_vals) > len(global_times):
                global_times = t_vals
                global_time_labels = t_lbls

            parts[pid] = PartitionInfo(
                id=pid,
                name=pname,
                path=zf,
                bounds_epsg3826=[bbox_xmin, bbox_ymin, bbox_xmax, bbox_ymax],
                bounds_wgs84=[bw, bs, be, bn],
                shape=[len(y_vals), len(x_vals)],
                transform=list(tf)[:6],
                times=t_vals,
                var_name=var
            )
        except Exception as ex:
            print(f"警告: 無法讀取分區 {zf}: {ex}")

    if not parts:
        raise ValueError("無有效之 ZARR 分區資料")

    catalog.current_path = str(p)
    catalog.partitions = parts
    catalog.union_bounds_3826 = [all_xmin, all_ymin, all_xmax, all_ymax]
    catalog.union_bounds_wgs84 = [all_w, all_s, all_e, all_n]
    catalog.times = global_times
    catalog.time_labels = global_time_labels
    return catalog

try:
    scan_directory(catalog.current_path)
    print(f"成功載入預設資料庫: {len(catalog.partitions)} 個分區")
except Exception as e:
    print(f"初始目錄掃描提示: {e}")

@app.on_event("startup")
def startup_event():
    try:
        if not catalog.partitions:
            scan_directory(catalog.current_path)
    except Exception as e:
        print(f"啟動掃描提示: {e}")

@app.get("/api/catalog")
def get_catalog():
    start_label = catalog.time_labels[0] if catalog.time_labels else ""
    end_label = catalog.time_labels[-1] if catalog.time_labels else ""
    return {
        "current_path": catalog.current_path,
        "partition_count": len(catalog.partitions),
        "partitions": [vars(p) for p in catalog.partitions.values()],
        "union_bounds_3826": catalog.union_bounds_3826,
        "union_bounds_wgs84": catalog.union_bounds_wgs84,
        "times": catalog.times,
        "time_labels": catalog.time_labels,
        "start_time": start_label,
        "end_time": end_label
    }

@app.post("/api/catalog/scan")
def set_catalog_path(path: str = Form(...)):
    try:
        scan_directory(path)
        return get_catalog()
    except Exception as e:
        raise HTTPException(400, detail=str(e))

@app.get("/api/partition/{pid}/depth/{frame_idx}.png")
def get_partition_depth_png(
    pid: str,
    frame_idx: int,
    opacity_scale: float = 1.0,
    color_scheme: str = "standard",
    show_shallow: bool = False
):
    if pid not in catalog.partitions:
        raise HTTPException(404, "找不到指定分區")
    pinfo = catalog.partitions[pid]
    try:
        ds = xr.open_zarr(pinfo.path, consolidated=False)
        frame_idx = max(0, min(frame_idx, len(ds.time) - 1))
        arr = ds[pinfo.var_name].isel(time=frame_idx).values.astype("f4")
        
        # Warp to EPSG:3857 for web map
        tf = Affine(*pinfo.transform)
        bounds_3826 = pinfo.bounds_epsg3826
        w, s, e, n = transform_bounds("EPSG:3826", "EPSG:3857", *bounds_3826, densify_pts=15)
        
        # 依據 5m 網格與 2.5m 定位精度，輸出採用 1:1 原生網格尺寸進行 Web Mercator 重投影
        out_w, out_h = pinfo.shape[1], pinfo.shape[0]
        output = np.full((out_h, out_w), np.nan, dtype="f4")
        
        reproject(
            arr, output,
            src_transform=tf, src_crs="EPSG:3826", src_nodata=np.nan,
            dst_transform=from_bounds(w, s, e, n, out_w, out_h), dst_crs="EPSG:3857",
            dst_nodata=np.nan, resampling=Resampling.nearest
        )
        
        rgba = np.zeros((out_h, out_w, 4), dtype="u1")
        
        # 門檻遮罩與分級著色 (依使用者指定標準色階)
        # 1. 0.1m ~ 0.3m: RGB(198, 219, 239) 透明度 70% (Alpha 178) - 依手冊規範預設隱藏
        if show_shallow:
            m1 = (output >= 0.1) & (output < 0.3)
            rgba[m1, 0] = 198; rgba[m1, 1] = 219; rgba[m1, 2] = 239
            rgba[m1, 3] = int(np.clip(178 * opacity_scale, 0, 255))
        
        # 2. 0.3m ~ 0.5m: RGB(198, 219, 239) 透明度 40% (Alpha 102)
        m2 = (output >= 0.3) & (output < 0.5)
        rgba[m2, 0] = 198; rgba[m2, 1] = 219; rgba[m2, 2] = 239
        rgba[m2, 3] = int(np.clip(102 * opacity_scale, 0, 255))
        
        # 3. 0.5m ~ 1.0m: RGB(120, 180, 214) 透明度 40% (Alpha 102)
        m3 = (output >= 0.5) & (output < 1.0)
        rgba[m3, 0] = 120; rgba[m3, 1] = 180; rgba[m3, 2] = 214
        rgba[m3, 3] = int(np.clip(102 * opacity_scale, 0, 255))
        
        # 4. 1.0m ~ 2.0m: RGB(66, 146, 198) 透明度 40% (Alpha 102)
        m4 = (output >= 1.0) & (output < 2.0)
        rgba[m4, 0] = 66; rgba[m4, 1] = 146; rgba[m4, 2] = 198
        rgba[m4, 3] = int(np.clip(102 * opacity_scale, 0, 255))
        
        # 5. 2.0m ~ 3.0m: RGB(37, 81, 156) 透明度 40% (Alpha 102)
        m5 = (output >= 2.0) & (output < 3.0)
        rgba[m5, 0] = 37; rgba[m5, 1] = 81; rgba[m5, 2] = 156
        rgba[m5, 3] = int(np.clip(102 * opacity_scale, 0, 255))
        
        # 6. > 3.0m: RGB(8, 48, 107) 透明度 40% (Alpha 102)
        m6 = output >= 3.0
        rgba[m6, 0] = 8; rgba[m6, 1] = 48; rgba[m6, 2] = 107
        rgba[m6, 3] = int(np.clip(102 * opacity_scale, 0, 255))
        
        # 備用警示配色方案 (例如 藍-黃-紅 災害警示模式)
        if color_scheme == "hazard":
            rgba[m4, 0] = 254; rgba[m4, 1] = 178; rgba[m4, 2] = 76  # 橙色
            rgba[m5, 0] = 240; rgba[m5, 1] = 59;  rgba[m5, 2] = 32  # 橙紅
            rgba[m6, 0] = 189; rgba[m6, 1] = 0;   rgba[m6, 2] = 38  # 深紅
        
        img_buf = io.BytesIO()
        Image.fromarray(rgba).save(img_buf, format="PNG")
        return Response(img_buf.getvalue(), media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})
    except Exception as e:
        raise HTTPException(500, detail=str(e))

@app.get("/api/query/point")
def query_point_timeseries(lng: float, lat: float):
    # Convert WGS84 to EPSG:3826 (TWD97 / TM2)
    x3826, y3826 = transformer_4326_to_3826.transform(lng, lat)
    
    hits = []
    num_steps = len(catalog.times) if catalog.times else 13
    composite_series = np.zeros(num_steps, dtype="f4")
    hit_partitions = []

    for pid, pinfo in catalog.partitions.items():
        xmin, ymin, xmax, ymax = pinfo.bounds_epsg3826
        if xmin <= x3826 <= xmax and ymin <= y3826 <= ymax:
            try:
                ds = xr.open_zarr(pinfo.path, consolidated=False)
                # 取得最接近網格點的時序水深 (5m 網格，最近鄰點距離容差 <= 2.5m)
                nearest_ds = ds[pinfo.var_name].sel(x=x3826, y=y3826, method="nearest")
                grid_x = float(nearest_ds.x.values)
                grid_y = float(nearest_ds.y.values)
                dist = float(np.hypot(grid_x - x3826, grid_y - y3826))
                
                val_series = nearest_ds.values
                series_clean = np.array([float(np.nan_to_num(v, nan=0.0)) for v in val_series], dtype="f4")
                
                # 僅在有數值時納入統計
                if len(series_clean) == num_steps:
                    composite_series = np.maximum(composite_series, series_clean)
                
                hits.append({
                    "partition_id": pid,
                    "partition_name": pinfo.name,
                    "grid_coord_3826": [round(grid_x, 2), round(grid_y, 2)],
                    "distance_to_click_m": round(dist, 2),
                    "water_depth_series": [round(float(x), 4) for x in series_clean],
                    "max_depth": round(float(np.max(series_clean)), 4),
                    "final_depth": round(float(series_clean[-1]), 4) if len(series_clean) > 0 else 0.0
                })
                hit_partitions.append(pinfo.name)
            except Exception as e:
                print(f"查詢分區 {pid} 失敗: {e}")
                
    return {
        "query_coord": {
            "lng": round(lng, 6),
            "lat": round(lat, 6),
            "x_twd97": round(x3826, 2),
            "y_twd97": round(y3826, 2)
        },
        "times": catalog.times,
        "time_labels": catalog.time_labels,
        "composite_series": [round(float(x), 4) for x in composite_series],
        "composite_max_depth": round(float(np.max(composite_series)), 4),
        "hit_count": len(hits),
        "hit_partitions": hit_partitions,
        "hits": hits
    }

# Mount Web Assets
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
