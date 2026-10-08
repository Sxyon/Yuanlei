"""生成隔离阅读演示用的十二页合成 PDF，不读取业务文件。"""
from pathlib import Path

def generate():
    """写入有限、固定内容的合成阅读样本。"""
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'']
    objects.append(b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
    pages = []
    for n in range(1, 13):
        page_id = len(objects) + 1
        pages.append(page_id)
        objects.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> /Contents {page_id + 1} 0 R >>'.encode())
        content = f'BT /F1 18 Tf 50 780 Td (Synthetic checklist - page {n} / 12) Tj 0 -40 Td /F1 12 Tf (U3 prototype only. No real procurement evidence.) Tj 0 -30 Td (Verify three-year scope, tax basis and source trace.) Tj ET'.encode()
        objects.append(b'<< /Length ' + str(len(content)).encode() + b' >>\nstream\n' + content + b'\nendstream')
    objects[1] = f'<< /Type /Pages /Count 12 /Kids [{" ".join(str(p) + " 0 R" for p in pages)}] >>'.encode()
    output = bytearray(b'%PDF-1.4\n'); offsets = [0]
    for n, obj in enumerate(objects, 1):
        offsets.append(len(output)); output.extend(f'{n} 0 obj\n'.encode() + obj + b'\nendobj\n')
    start = len(output); output.extend(f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]: output.extend(f'{offset:010} 00000 n \n'.encode())
    output.extend(f'trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode())
    target = Path(__file__).parent / 'samples' / 'checklist.pdf'
    target.parent.mkdir(exist_ok=True); target.write_bytes(output)

if __name__ == '__main__':
    generate()
