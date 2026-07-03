# Rotation Ops — Daily Theme Tracker

Daily US sector/theme rotation dashboard. ข้อมูลอัพเดตอัตโนมัติทุกวันหลังตลาด US ปิด (~05:30 เวลาไทย) ผ่าน GitHub Actions — ไม่ต้องใช้เครื่องตัวเอง

**สถาปัตยกรรม:** `fetch_data.py` รันบน GitHub Actions → ดึงราคา EOD (yfinance) → คำนวณ returns / RRG (weekly) / breadth 20DMA / dollar vol ratio → เขียน `data.json` + `history.json` → GitHub Pages เสิร์ฟ `index.html` ที่อ่านไฟล์นั้น

**Data discipline:** sourced-or-null (ticker ที่ดึงไม่ได้ = ตัดออก + แจ้งใน DATA QUALITY ไม่มีการประมาณค่า) · SEED_VERSION ใน `baskets.json` · ทุกค่ามี commit history ตรวจย้อนได้

---

## Setup ครั้งเดียว (ทำจากเบราว์เซอร์ได้ทั้งหมด)

1. **สร้าง repo** — กด `+` มุมขวาบน → New repository → ตั้งชื่อ เช่น `rotation-ops` → เลือก **Public** (จำเป็นสำหรับ Pages ฟรี) → Create
2. **เพิ่มไฟล์ทั้ง 5** — ในหน้า repo กด `Add file → Create new file` ทีละไฟล์ copy เนื้อหามาวาง:
   - `baskets.json`
   - `fetch_data.py`
   - `index.html`
   - `README.md`
   - `.github/workflows/update.yml` ← พิมพ์ path นี้ในช่องชื่อไฟล์ตรง ๆ (มีจุดนำหน้า) GitHub จะสร้างโฟลเดอร์ให้เอง
3. **เปิดสิทธิ์ให้ bot เขียนไฟล์** — Settings → Actions → General → Workflow permissions → เลือก **Read and write permissions** → Save
4. **รันรอบแรก** — แท็บ Actions → "Daily data update" → Run workflow → รอ ~2-3 นาที ถ้าขึ้นเขียวแปลว่า `data.json` ถูกสร้างแล้ว (เช็คได้ในหน้า repo)
5. **เปิด Pages** — Settings → Pages → Source: Deploy from a branch → Branch: `main` / `(root)` → Save → รอ 1-2 นาที URL จะเป็น `https://<username>.github.io/rotation-ops/`
6. **Bookmark URL นั้นบนมือถือ** — จบ หลังจากนี้ข้อมูลใหม่มาเองทุกเช้า

## การใช้งานประจำ

- เปิดหน้าเว็บตอนเช้า เช็ค **DATA QUALITY** ก่อนเชื่อตัวเลขเสมอ
- ตั้ง **Regime Gate** บนหัวหน้าเว็บให้ตรงกับผล LiquidityImpulseTracker + Hartnett Tracker ทุกสัปดาห์ (ค่าเก็บในเครื่อง ไม่ sync ข้ามอุปกรณ์ — ตั้งในมือถือเครื่องที่ใช้ดู)
- **★ ปักหมุด**ธีมที่ถือ position — จะลอยขึ้นบนสุด + alert ของธีมนั้นเป็นระดับ severe

## กติกาแก้ไข (Amendment Rule)

- เปลี่ยนสมาชิก basket ใด ๆ → แก้ `baskets.json` + bump `SEED_VERSION` + เขียนเหตุผลใน changelog ด้านล่าง
- เปลี่ยน threshold (breadth 50/30, alert 25pts, RRG window 14w) → ต้องมี rationale จากข้อมูลจริง 8-12 สัปดาห์ก่อน เหมือน REGIME_PROTOCOL_v1

### Changelog

- `1.0.0` (2026-07-03) — initial seed: 26 ธีม + 11 sector ETF ตามต้นแบบ taesk126 + Copper (custom, สมาชิกรอ review)

## ข้อจำกัดที่ต้องรู้

- yfinance เป็น unofficial source — เสถียรพอสำหรับ EOD แต่มีวันสะดุดได้ ระบบจะ flag ให้เห็นแทนที่จะเงียบ
- RRG ใช้ z-score approximation ไม่ใช่สูตร JdK ตัวจริง — quadrant ใกล้เส้น 100 อ่านด้วยความระวัง
- breadth ของ basket 3-5 ตัว (Quantum, Gold Miners, Copper) น้ำหนักทางสถิติต่ำ — ใช้เป็นบริบท ไม่ใช่สัญญาณเดี่ยว
- นี่คือเครื่องมือเฝ้าระวัง ไม่ใช่เครื่องกำเนิดสัญญาณซื้อขาย — การเข้า/ออกยังอยู่ที่ gate รายสัปดาห์ + Hull + tranche discipline
