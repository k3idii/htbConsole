import os
import shlex
import subprocess

from ..httpApi import async_download

DEFAULT_ZIP_PASSWORD = "hackthebox"
DEFAULT_UNPACK_CMD = "7z -o./unpacked/ -p{password} x {file}"


def execute_shell(cmd):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    return p.communicate()


def execute_unpack(dir_path, filename, password=None, unpack_cmd=None):
    safe_dir = shlex.quote(dir_path)
    safe_file = shlex.quote(filename)
    pw = password or DEFAULT_ZIP_PASSWORD
    template = unpack_cmd or DEFAULT_UNPACK_CMD

    cmd = template.format(
        password=pw,
        file=safe_file,
        dir=safe_dir,
        filename=filename,
    )
    full_cmd = f"cd {safe_dir} && {cmd}"
    output = execute_shell(full_cmd)
    log_fn = os.path.join(dir_path, f"{filename}._log")
    with open(log_fn, "ab") as f:
        f.write(b"\n-----\n".join(output))
    return True


async def async_download_and_extract(chall_data, url, password=None, unpack_cmd=None):
    chall_dir = chall_data['real_dir_name']
    real_fn = chall_data.get('file_name', 'task.zip')
    ext = real_fn.split(".")[-1]
    filename = f"task.{ext}"
    out_file = os.path.join(chall_dir, filename)

    os.makedirs(chall_dir, exist_ok=True)

    size = await async_download(url, out_file)
    result = f"Saved {size} bytes to {out_file}"

    if ext in ['zip', '7z', 'tar', 'gz', 'rar']:
        execute_unpack(chall_dir, filename, password=password, unpack_cmd=unpack_cmd)
        result += " | Extracted"

    return result
