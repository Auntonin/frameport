"""Assemble only distributable files; never copy user inputs or application state."""
from hashlib import sha256
from importlib.metadata import distribution
from pathlib import Path
import shutil
import sys
from importer.runtime import VERSION

ROOT = Path(__file__).resolve().parent
release = ROOT / "release"
package = release / "FramePort"
assert (package / "FramePort.exe").is_file()
(package / "START-HERE.txt").write_text("""FramePort 1.0.0 - Windows x64

วิธีเปิด
1. แตก ZIP ทั้งโฟลเดอร์ก่อน อย่าเปิด EXE จากข้างใน ZIP
2. เปิด FramePort.exe โดยเก็บโฟลเดอร์ _internal ไว้ข้างกัน
3. ตั้งค่าขั้นสูง → เปลี่ยน API profile เลือก profile ส่วนตัว แล้วใส่ URL เว็บไซต์
   profiles/example.json เป็นตัวอย่างจำลองเท่านั้น จากนั้นกด เข้าสู่ระบบผ่านเว็บไซต์
4. ล็อกอินด้วยบัญชี Admin ใน Edge/Chrome ที่โปรแกรมเปิดให้
5. เลือก Excel/CSV และโฟลเดอร์ภาพ แล้วกด เริ่มนำเข้า
   ปุ่ม ดูตัวอย่าง ใช้เมื่อต้องการตรวจภาพก่อน ไม่จำเป็นต้องกดก่อนนำเข้า

ข้อมูล
- A ไม่ใช้ B = latitude,longitude C = ชื่อ D = รายละเอียด
- ภาพเรียงตามชื่อแบบตัวเลข ทุก 5 ภาพต่อ 1 แถว
- เลือก แถวแรกเป็นหัวตาราง ให้ตรงกับไฟล์จริง
- WebP ที่ตรงข้อจำกัด API ใช้ไฟล์เดิม ไม่แปลงหรือสำรองซ้ำ
- ภาพชนิดอื่นแปลงเป็น WebP โดยคงความละเอียด และจำกัดตาม API profile
- ค่าเริ่มต้น 5 MiB/ภาพ เปลี่ยนเมื่อเว็บไซต์รองรับขนาดใหม่แล้วเท่านั้น
- หากหยุดหรือปิด ให้เริ่มต่อด้วยเว็บไซต์/ข้อมูลเดิม โปรแกรมข้ามรายการสำเร็จ
- คำขอค้าง: ตรวจเว็บไซต์ก่อนอนุญาตส่งซ้ำผ่านปุ่ม รายการค้าง

ไม่ต้องติดตั้ง Python ต้องมี Edge/Chrome และอินเทอร์เน็ตสำหรับเว็บไซต์ปลายทาง
ค่าตั้งค่า ประวัติ และเบราว์เซอร์อยู่ที่ %LOCALAPPDATA%/FramePort
ก่อนย้ายไปเครื่องอื่น ให้เก็บประวัติเดิมด้วยหากต้องการป้องกันนำเข้าซ้ำ
ZIP นี้ไม่รวมภาพ Excel รหัสผ่าน หรือ session ส่วนตัว

โปรแกรมนี้ยังไม่ได้ลงลายเซ็นดิจิทัลผู้เผยแพร่
SHA256SUMS.txt ใช้ตรวจสอบไฟล์ให้ตรงกับชุดที่ได้รับ ไม่ใช่หลักฐานผู้เผยแพร่ที่รับรองแล้ว
""", encoding="utf-8-sig")
licenses = package / "THIRD-PARTY-LICENSES"
licenses.mkdir(exist_ok=True)
versions = []
for name in ("pillow", "openpyxl", "requests", "playwright", "greenlet", "pyee", "charset-normalizer", "idna", "urllib3", "certifi", "et-xmlfile", "pyinstaller"):
    dist = distribution(name)
    versions.append(name + " " + dist.version)
    for entry in dist.files or []:
        if any(marker in str(entry).lower() for marker in ("license", "copying", "notice")) and dist.locate_file(entry).is_file():
            target = licenses / name / str(entry).replace("..", "_")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(dist.locate_file(entry), target)
python_license = Path(sys.base_prefix) / "LICENSE.txt"
if python_license.is_file():
    shutil.copyfile(python_license, licenses / "Python-LICENSE.txt")
for product in ("tcl8.6", "tk8.6"):
    source = Path(sys.base_prefix) / "tcl" / product / "license.terms"
    if source.is_file():
        shutil.copyfile(source, licenses / (product + "-license.terms"))
(licenses / "VERSIONS.txt").write_text("\n".join(versions), encoding="utf-8")
# Per-file manifest for the portable directory, then a separate ZIP checksum.
manifest = []
for file in sorted(package.rglob("*")):
    if file.is_file() and file.name != "SHA256SUMS.txt":
        manifest.append(sha256(file.read_bytes()).hexdigest() + "  " + file.relative_to(package).as_posix())
(package / "SHA256SUMS.txt").write_text("\n".join(manifest) + "\n", encoding="utf-8")
archive = Path(shutil.make_archive(str(release / ("FramePort-" + VERSION + "-windows-x64")), "zip", release, package.name))
archive.with_suffix(".sha256").write_text(sha256(archive.read_bytes()).hexdigest() + "  " + archive.name + "\n", encoding="ascii")
print(archive)
