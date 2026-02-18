#!/usr/bin/env python3
# roles/common/files/combine_reports.py
import datetime
import glob
import os
import shutil
import sys
from collections import defaultdict

# Configuration
RETENTION_DAYS = 7


def ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)


def combine_run_reports(root_dir, run_id):
    """
    Reads from Split/*/<RunID>/**/*
    Writes to Combined/<RunID>/ReportName.csv
    """
    # FIX: Updated path to look inside Role folders AND Host subfolders
    # Structure: root/Split/ubuntu/2026-01-29/web01/file.csv
    search_path = os.path.join(root_dir, "Split", "*", run_id, "**", "*.csv")

    dest_dir = os.path.join(root_dir, "Combined", run_id)

    # Recursive glob to find all CSVs for this Run ID, regardless of Role or Host
    files = glob.glob(search_path, recursive=True)

    if not files:
        print(f"No reports found for run {run_id} in {search_path}")
        return

    print(f"--- Combining Reports for Run ID: {run_id} ---")
    ensure_dir(dest_dir)

    # 1. Group files by Report Name
    groups = defaultdict(list)

    for f in files:
        filename = os.path.basename(f)
        # Logic: "security_users_web01.csv" -> "security_users"
        # If the file ends with _global.csv, remove that too.
        if "_" in filename:
            name_part = filename.rsplit("_", 1)[0]
            report_name = name_part
        else:
            report_name = os.path.splitext(filename)[0]

        groups[report_name].append(f)

    # 2. Merge and Write
    for report_name, file_list in groups.items():
        output_file = os.path.join(dest_dir, f"{report_name}.csv")
        print(
            f"Creating {os.path.basename(output_file)} (from {len(file_list)} files)..."
        )

        try:
            with open(output_file, "w", encoding="utf-8") as outfile:
                # Read header from the first file
                with open(file_list[0], "r", encoding="utf-8") as first:
                    header = first.readline()
                    outfile.write(header)

                # Append content from all files
                for f in file_list:
                    with open(f, "r", encoding="utf-8") as infile:
                        first_line = infile.readline()  # Read header
                        # Safety check: Ensure header matches (optional, but good)
                        if first_line != header:
                            # If headers don't match, this might be a different file type
                            # But usually we just assume they match for speed.
                            pass

                        shutil.copyfileobj(infile, outfile)
        except Exception as e:
            print(f"Error combining {report_name}: {e}")


def get_folder_date(folder_name):
    """Helper to extract date object from folder name string"""
    try:
        # Try full timestamp: 2026-01-26_123000
        return datetime.datetime.strptime(folder_name, "%Y-%m-%d_%H%M%S").date()
    except ValueError:
        try:
            # Fallback to date only: 2026-01-26
            return datetime.datetime.strptime(folder_name, "%Y-%m-%d").date()
        except ValueError:
            return None


def archive_directory_contents(base_path, archive_root_base, cutoff_date):
    """
    Scans a specific directory for timestamped folders and archives them.
    """
    if not os.path.exists(base_path):
        return

    for folder_name in os.listdir(base_path):
        folder_path = os.path.join(base_path, folder_name)

        if not os.path.isdir(folder_path):
            continue

        folder_date = get_folder_date(folder_name)
        if not folder_date:
            continue  # Not a timestamp folder

        if folder_date < cutoff_date:
            # Replicate structure in archive
            # e.g., archive/Split/ubuntu/2026-01-01.zip
            rel_path = os.path.relpath(folder_path, start=os.path.dirname(base_path))
            dest_dir = os.path.join(archive_root_base, os.path.dirname(rel_path))
            ensure_dir(dest_dir)

            archive_name = os.path.join(dest_dir, folder_name)

            print(f"Archiving {folder_path} -> {archive_name}.zip")
            try:
                shutil.make_archive(archive_name, "zip", folder_path)
                shutil.rmtree(folder_path)
            except Exception as e:
                print(f"Failed to archive {folder_path}: {e}")


def archive_old_folders(root_dir):
    """
    Archives folders in Combined/ and Split/<Role>/ based on date.
    """
    print(f"--- Archiving Folders Older Than {RETENTION_DAYS} Days ---")
    cutoff_date = datetime.date.today() - datetime.timedelta(days=RETENTION_DAYS)
    archive_root = os.path.join(root_dir, "archive")

    # 1. Archive Combined/ (Flat structure: Combined/<Timestamp>)
    archive_directory_contents(
        os.path.join(root_dir, "Combined"),
        os.path.join(archive_root, "Combined"),
        cutoff_date,
    )

    # 2. Archive Split/ (Nested structure: Split/<Role>/<Timestamp>)
    split_root = os.path.join(root_dir, "Split")
    if os.path.exists(split_root):
        for role_name in os.listdir(split_root):
            role_path = os.path.join(split_root, role_name)
            if os.path.isdir(role_path):
                # Check inside the role folder for timestamp folders
                archive_directory_contents(
                    role_path,
                    os.path.join(archive_root, "Split", role_name),
                    cutoff_date,
                )


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "."

    # Optional 2nd arg: Run ID (timestamp)
    run_id = sys.argv[2] if len(sys.argv) > 2 else None

    if os.path.isdir(path):
        if run_id:
            combine_run_reports(path, run_id)
        else:
            print("No Run ID provided, skipping combination.")

        archive_old_folders(path)
    else:
        print(f"Error: Directory not found: {path}")
