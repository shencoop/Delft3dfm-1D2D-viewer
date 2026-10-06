"""
Delft3D-FM 模式輸出 NetCDF (map.nc / fou.nc) 自動轉 Zarr 與 COG GeoTIFF 工具
Delft3D-FM Output Converter: Map/Fou NetCDF to Zarr & Cloud Optimized GeoTIFF (COG)

功能說明:
1. 自動掃描指定目錄下所有 Delft3D-FM 模式輸出檔案 (*_map.nc, *_fou.nc)。
2. 自動判讀分區數量 (Partition Count, e.g. 0000~0010) 與空間坐標邊界。
3. 自動解析時間序列水深 (Mesh2d_waterdepth / s1 / dep)，轉換並封裝為 Zarr 分塊格式。
4. 自動提取最大淹水深度 (Max Inundation Depth，來自 fou.nc 或 map.nc 全時段最大值)，產製附帶金字塔 (Overviews) 之標準 COG GeoTIFF。
5. 支援 CLI 命令與批次執行，完全配合 Delft3D-FM 多分區展示圖台之資料夾架構。
"""

import argparse
import glob
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import Affine, from_bounds
from rasterio.warp import transform_bounds, Resampling, reproject
import xarray as xr

# 強制 UTF-8 輸出以防繁體中文終端編碼問題
sys.stdout.reconfigure(encoding='utf-8')


def detect_dfm_partitions(input_dir: str) -> Dict[str, Dict[str, str]]:
    """
    自動掃描目錄中的 Delft3D-FM 輸出檔案，判讀分區數量與對應的 map.nc / fou.nc
    回傳字典格式:
    {
        "0000": {"map": "/path/to/..._0000_map.nc", "fou": "/path/to/..._0000_fou.nc"},
        "0001": {"map": "/path/to/..._0001_map.nc", "fou": "..."},
        ...
    }
    """
    p = Path(input_dir).resolve()
    if not p.exists():
        raise FileNotFoundError(f"找不到指定的輸入資料夾: {input_dir}")

    # 搜尋所有 map.nc 與 fou.nc
    map_files = sorted(glob.glob(str(p / "*_map.nc")) + glob.glob(str(p / "**" / "*_map.nc"), recursive=True))
    fou_files = sorted(glob.glob(str(p / "*_fou.nc")) + glob.glob(str(p / "**" / "*_fou.nc"), recursive=True))

    partitions = {}

    # 1. 解析 map.nc
    for mf in map_files:
        basename = os.path.basename(mf)
        # 尋找 4 位數分區編號 (例如 FlowFM_0000_map.nc)
        m = re.search(r'_(\d{4})_map\.nc$', basename, re.IGNORECASE)
        part_id = m.group(1) if m else "single"
        if part_id not in partitions:
            partitions[part_id] = {}
        partitions[part_id]["map"] = mf

    # 2. 解析 fou.nc
    for ff in fou_files:
        basename = os.path.basename(ff)
        m = re.search(r'_(\d{4})_fou\.nc$', basename, re.IGNORECASE)
        part_id = m.group(1) if m else "single"
        if part_id not in partitions:
            partitions[part_id] = {}
        partitions[part_id]["fou"] = ff

    return dict(sorted(partitions.items()))


def extract_dfm_grid_metadata(ds: xr.Dataset, crs_default: str = "EPSG:3826") -> Tuple[np.ndarray, np.ndarray, Affine, float, float]:
    """
    從 Delft3D-FM NetCDF 萃取 X, Y 坐標、解析度 dx, dy 與像素邊界 Affine Transform
    """
    # 判斷 x, y 變數名稱 (支援 Mesh2d_face_x, x, FlowElem_x 等)
    x_var = None
    y_var = None
    for cand_x in ["Mesh2d_face_x", "x", "FlowElem_x", "grid_x"]:
        if cand_x in ds:
            x_var = cand_x
            break
    for cand_y in ["Mesh2d_face_y", "y", "FlowElem_y", "grid_y"]:
        if cand_y in ds:
            y_var = cand_y
            break

    if "x" in ds.coords and "y" in ds.coords:
        x_vals = ds.coords["x"].values
        y_vals = ds.coords["y"].values
    elif x_var and y_var:
        x_vals = ds[x_var].values
        y_vals = ds[y_var].values
    else:
        raise ValueError("無法在 NetCDF 中識別二維網格 x, y 坐標變數")

    # 若為 1D 陣列 (已結構化網格)
    if x_vals.ndim == 1 and y_vals.ndim == 1:
        dx = float(abs(x_vals[1] - x_vals[0])) if len(x_vals) > 1 else 5.0
        dy = float(abs(y_vals[1] - y_vals[0])) if len(y_vals) > 1 else 5.0
        top_y = y_vals[0] if y_vals[0] > y_vals[-1] else y_vals[-1]
        left_x = x_vals[0] if x_vals[0] < x_vals[-1] else x_vals[-1]
        y_sign = -dy if y_vals[0] > y_vals[-1] else dy
        x_sign = dx if x_vals[0] < x_vals[-1] else -dx
        tf = Affine(x_sign, 0.0, left_x - dx / 2.0, 0.0, y_sign, top_y + dy / 2.0)
    else:
        # 若為 2D 矩陣或非結構化網格，計算邊界與推估解析度
        xmin, xmax = float(np.nanmin(x_vals)), float(np.nanmax(x_vals))
        ymin, ymax = float(np.nanmin(y_vals)), float(np.nanmax(y_vals))
        dx, dy = 5.0, 5.0
        tf = Affine(dx, 0.0, xmin, 0.0, -dy, ymax)

    return x_vals, y_vals, tf, dx, dy


def rasterize_dfm_faces_to_grid(
    fx: np.ndarray,
    fy: np.ndarray,
    values_2d: np.ndarray,
    res: Optional[float] = None,
    buffer_cells: int = 4,
    crs_code: str = "EPSG:3826"
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, Affine]:
    """
    將 Delft3D-FM 非結構網格面 (Mesh2d_nFaces) 坐標與數值映射至標準 2D 結構化網格
    支援三組權威坐標系:
      - 台灣本島 121: EPSG:3826 (預設解析度 5.0m)
      - 台灣離島 (澎湖/馬祖/金門) 119: EPSG:3825 (預設解析度 5.0m)
      - 全球 / WGS 84 經緯度: EPSG:4326 (預設解析度 0.00005度 ~ 5m)
    """
    # 若未指定解析度，依據坐標系自動給予黃金標準解析度
    if res is None or res <= 0:
        if crs_code.upper() in ["EPSG:4326", "WGS84", "CRS84"]:
            res = 0.00005  # 約 5.5 公尺
        else:
            res = 5.0      # 公尺

    xmin, xmax = float(np.nanmin(fx)), float(np.nanmax(fx))
    ymin, ymax = float(np.nanmin(fy)), float(np.nanmax(fy))

    # 計算對齊之網格邊界 (全域標準錨定)
    grid_xmin = np.floor(xmin / res) * res - (buffer_cells * res) + (res / 2.0)
    grid_xmax = np.ceil(xmax / res) * res + (buffer_cells * res) - (res / 2.0)
    grid_ymin = np.floor(ymin / res) * res - (buffer_cells * res) + (res / 2.0)
    grid_ymax = np.ceil(ymax / res) * res + (buffer_cells * res) - (res / 2.0)

    x_coords = np.arange(grid_xmin, grid_xmax + res / 2.0, res, dtype=np.float64)
    y_coords = np.arange(grid_ymax, grid_ymin - res / 2.0, -res, dtype=np.float64)

    nx = len(x_coords)
    ny = len(y_coords)

    # 網格索引映射
    col_idx = np.clip(np.round((fx - grid_xmin) / res).astype(int), 0, nx - 1)
    row_idx = np.clip(np.round((grid_ymax - fy) / res).astype(int), 0, ny - 1)

    tf = Affine(res, 0.0, grid_xmin - res / 2.0, 0.0, -res, grid_ymax + res / 2.0)

    if values_2d.ndim == 2:
        nt = values_2d.shape[0]
        grid_data = np.zeros((nt, ny, nx), dtype=np.float32)
        for t in range(nt):
            grid_data[t, row_idx, col_idx] = values_2d[t]
    else:
        grid_data = np.zeros((ny, nx), dtype=np.float32)
        grid_data[row_idx, col_idx] = values_2d

    return grid_data, x_coords, y_coords, tf


def convert_map_nc_to_zarr(
    nc_path: str,
    output_zarr_path: str,
    var_name: str = "Mesh2d_waterdepth",
    crs_code: str = "EPSG:3826",
    res: Optional[float] = None
) -> str:
    """
    將 Delft3D-FM map.nc 時序檔案轉換為標準分塊 Zarr 格式
    """
    print(f"🔄 正在讀取 map.nc: {nc_path}")
    ds = xr.open_dataset(nc_path)

    # 取得網格面中心點坐標
    fx = ds.Mesh2d_face_x.values
    fy = ds.Mesh2d_face_y.values

    # 自動判斷坐標系 (若資料集坐標值為經緯度範圍且未明確指定)
    if crs_code == "EPSG:3826" and (np.nanmax(fx) <= 180.0 and np.nanmin(fx) >= -180.0):
        print("   ℹ️ 偵測到經緯度坐標範圍，自動調整坐標系為 EPSG:4326")
        crs_code = "EPSG:4326"

    target_var = var_name if var_name in ds else ("waterdepth" if "waterdepth" in ds else list(ds.data_vars.keys())[0])
    raw_data = ds[target_var].values  # shape: (time, Mesh2d_nFaces)

    print(f"   提取時序變數: [{target_var}] | 面數: {len(fx)} | 時間步數: {len(ds.time)} | 坐標系: {crs_code}")

    grid_data, x_coords, y_coords, tf = rasterize_dfm_faces_to_grid(fx, fy, raw_data, res=res, crs_code=crs_code)

    # 構建結構化 Dataset
    ds_out = xr.Dataset(
        data_vars={
            "Mesh2d_waterdepth": (("time", "y", "x"), grid_data)
        },
        coords={
            "time": ds.time.values,
            "y": y_coords,
            "x": x_coords
        },
        attrs={
            "crs": crs_code,
            "spatial_ref": crs_code,
            "transform": list(tf)[:6],
            "institution": ds.attrs.get("institution", "Deltares"),
            "source": ds.attrs.get("source", "D-Flow FM")
        }
    )

    out_p = Path(output_zarr_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    print(f"   寫入 Zarr ({len(y_coords)}x{len(x_coords)})...")
    ds_out.to_zarr(str(out_p), mode="w", consolidated=True)
    print(f"   ✅ Zarr 轉換完成: {out_p.resolve()}")
    return str(out_p)


def convert_max_depth_to_cog(
    input_nc_path: str,
    output_tif_path: str,
    is_fou: bool = True,
    crs_code: str = "EPSG:3826",
    res: Optional[float] = None
) -> str:
    """
    從 fou.nc (或 map.nc) 萃取最大淹水深度並產製標準 COG GeoTIFF (含金字塔 Overviews)
    """
    print(f"🔄 正在產製最大淹水深度 COG GeoTIFF: {input_nc_path}")
    ds = xr.open_dataset(input_nc_path)

    fx = ds.Mesh2d_face_x.values
    fy = ds.Mesh2d_face_y.values

    # 1. 萃取水深最大值陣列
    target_var = None
    if is_fou:
        for cand in ["Mesh2d_fourier003_max_depth", "Mesh2d_fourier001_max", "Mesh2d_max_waterdepth", "max_depth"]:
            if cand in ds:
                target_var = cand
                break
        if not target_var:
            target_var = list(ds.data_vars.keys())[-1]
        raw_vals = ds[target_var].values
    else:
        target_var = "Mesh2d_waterdepth" if "Mesh2d_waterdepth" in ds else list(ds.data_vars.keys())[0]
        raw_vals = np.nanmax(ds[target_var].values, axis=0)

    print(f"   提取最大水深變數: [{target_var}]")
    grid_arr, x_coords, y_coords, tf = rasterize_dfm_faces_to_grid(fx, fy, raw_vals, res=res)
    grid_arr = np.nan_to_num(grid_arr, nan=-9999.0)
    ny, nx = grid_arr.shape

    out_p = Path(output_tif_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    # 5m 黃金網格與 COG 金字塔標準配置
    profile = {
        "driver": "GTiff",
        "height": ny,
        "width": nx,
        "count": 1,
        "dtype": "float32",
        "crs": crs_code,
        "transform": tf,
        "nodata": -9999.0,
        "tiled": True,
        "blockxsize": 512,
        "blockysize": 512,
        "compress": "lzw",
        "predictor": 2
    }

    with rasterio.open(out_p, "w", **profile) as dst:
        dst.write(grid_arr, 1)
        # 建立 5 階金字塔圖層 (Overviews): 10m, 20m, 40m, 80m, 160m
        dst.build_overviews([2, 4, 8, 16, 32], Resampling.nearest)
        dst.update_tags(ns="rio_overview", resampling="nearest")

    print(f"   ✅ COG GeoTIFF 產製完成 (5m 黃金網格，含 5 階金字塔 Overviews [2,4,8,16,32]): {out_p.resolve()}")
    return str(out_p)


def process_dfm_directory_pipeline(
    input_dir: str,
    output_dir: Optional[str] = None,
    crs_code: str = "EPSG:3826"
) -> Dict[str, Dict[str, str]]:
    """
    全自動批次處理流程：
    1. 掃描 input_dir 判斷所有分區 (0000~0010)
    2. 將各分區 map.nc 轉換為 .zarr
    3. 將各分區 fou.nc (或 map.nc) 轉換為 max_depth_cog.tif
    """
    partitions = detect_dfm_partitions(input_dir)
    if not partitions:
        print(f"⚠️ 在 {input_dir} 中未找到任何 Delft3D-FM 輸出檔案 (*_map.nc / *_fou.nc)")
        return {}

    target_out_dir = Path(output_dir or input_dir).resolve()
    print("=" * 70)
    print(f"🚀 Delft3D-FM 多分區自動轉檔管道啟動！")
    print(f"📁 輸入目錄: {input_dir}")
    print(f"📁 輸出目錄: {target_out_dir}")
    print(f"🧩 偵測到分區數量: {len(partitions)} 個分區 ({', '.join(partitions.keys())})")
    print("=" * 70)

    summary = {}

    for part_id, files in partitions.items():
        print(f"\n▶ 正在處理分區 [{part_id}]...")
        part_summary = {}

        # 1. 處理時序 map.nc -> zarr
        if "map" in files:
            base_name = Path(files["map"]).stem
            zarr_out = target_out_dir / f"{base_name}.zarr"
            convert_map_nc_to_zarr(files["map"], str(zarr_out), crs_code=crs_code)
            part_summary["zarr"] = str(zarr_out)

        # 2. 處理最大淹水深度 fou.nc -> COG GeoTIFF
        if "fou" in files:
            base_name = Path(files["fou"]).stem
            tif_out = target_out_dir / f"{base_name}_cog.tif"
            convert_max_depth_to_cog(files["fou"], str(tif_out), is_fou=True, crs_code=crs_code)
            part_summary["cog"] = str(tif_out)
        elif "map" in files:
            # 若無獨立 fou.nc，自 map.nc 全時段計算最大值
            base_name = Path(files["map"]).stem.replace("_map", "_max_depth")
            tif_out = target_out_dir / f"{base_name}_cog.tif"
            convert_max_depth_to_cog(files["map"], str(tif_out), is_fou=False, crs_code=crs_code)
            part_summary["cog"] = str(tif_out)

        summary[part_id] = part_summary

    # 輸出自動索引 metadata.json
    meta_path = target_out_dir / "partitions_metadata.json"
    with open(meta_path, "w", encoding="utf-8-sig") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 70)
    print(f"🎉 全部分區轉檔完成！元數據索引已儲存至: {meta_path}")
    print("=" * 70)
    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Delft3D-FM 模式輸出 (map.nc / fou.nc) 自動轉 Zarr 與 COG GeoTIFF 工具",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "-i", "--input-dir",
        required=True,
        help="Delft3D-FM 成果資料夾路徑 (包含 FlowFM_0000_map.nc / fou.nc 等)"
    )
    parser.add_argument(
        "-o", "--output-dir",
        default=None,
        help="輸出 Zarr 與 COG GeoTIFF 之目標資料夾 (預設輸出於輸入資料夾)"
    )
    parser.add_argument(
        "--crs",
        default="EPSG:3826",
        help="坐標系統代碼 (預設: EPSG:3826 TWD97/TM2)"
    )

    args = parser.parse_args()
    process_dfm_directory_pipeline(args.input_dir, args.output_dir, args.crs)


if __name__ == "__main__":
    main()
