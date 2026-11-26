"""Page detection, perspective correction and OCR line extraction."""
import base64
import csv
import io
import subprocess


def inspect_page(jpeg):
    import cv2
    import numpy as np

    image = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError('Could not decode the camera image.')
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 50, 150)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    height, width = gray.shape
    for contour in sorted(contours, key=cv2.contourArea, reverse=True):
        area = cv2.contourArea(contour) / (height * width)
        if area < .24:
            break
        corners = cv2.approxPolyDP(contour, .025 * cv2.arcLength(contour, True), True)
        if area > .94 or len(corners) != 4 or not cv2.isContourConvex(corners):
            continue
        points = corners.reshape(4, 2).astype(np.float32)
        diagonal = points[:, 0] + points[:, 1]
        cross = points[:, 0] - points[:, 1]
        ordered = points[[diagonal.argmin(), cross.argmax(), diagonal.argmax(), cross.argmin()]]
        if len(np.unique(ordered, axis=0)) != 4:
            continue
        if np.any(ordered < 4) or np.any(ordered >= [width - 4, height - 4]):
            continue
        tl, tr, br, bl = ordered
        w = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
        h = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
        if min(w, h) < 110:
            continue
        target = np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]])
        transform = cv2.getPerspectiveTransform(ordered, target)
        page = cv2.warpPerspective(gray, transform, (w, h))
        if cv2.Laplacian(page[8:-8, 8:-8], cv2.CV_64F).var() < 45:
            return {'status': 'Page is blurry. Hold steady or adjust focus.'}
        thumb = cv2.resize(page, (16, 16), interpolation=cv2.INTER_AREA)
        signature = ''.join('1' if value < thumb.mean() else '0' for value in thumb.flat)
        cleaned = cv2.normalize(page, None, 15, 245, cv2.NORM_MINMAX)
        ok, encoded = cv2.imencode('.jpg', cleaned, [cv2.IMWRITE_JPEG_QUALITY, 92])
        if not ok:
            raise ValueError('Could not encode the cleaned page.')
        return {'corners': ordered.round().astype(int).tolist(), 'signature': signature,
                'jpeg': base64.b64encode(encoded).decode('ascii')}
    return {'status': 'Fit all four page corners inside the frame.'}


def prepare_text_image(jpeg):
    """Deskew camera text by maximizing the separation between text rows."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return jpeg

    gray = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return jpeg
    height, width = gray.shape
    edges = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                  cv2.THRESH_BINARY_INV, 31, 12)
    # Exclude the frame edges, which often contain the border of a desk or screen.
    y, x = height // 10, width // 10
    inner = edges[y:height-y, x:width-x]
    h, w = inner.shape

    def row_score(angle):
        matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1)
        aligned = cv2.warpAffine(inner, matrix, (w, h), flags=cv2.INTER_NEAREST)
        rows = aligned[h//8:7*h//8, w//8:7*w//8].mean(axis=1)
        return float(np.var(rows))

    angle = max(range(-12, 13), key=row_score)
    if abs(angle) == 12 or row_score(angle) < 1.12 * row_score(0):
        angle = 0
    transform = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1)
    # Expand the canvas so straightening does not clip text at the corners.
    cosine, sine = abs(transform[0, 0]), abs(transform[0, 1])
    out_w = int(width * cosine + height * sine + .5)
    out_h = int(height * cosine + width * sine + .5)
    transform[0, 2] += (out_w - width) / 2
    transform[1, 2] += (out_h - height) / 2
    aligned = cv2.warpAffine(gray, transform, (out_w, out_h), borderValue=255)
    scale = max(1.0, min(2.5, 1500 / max(aligned.shape)))
    if scale > 1:
        aligned = cv2.resize(aligned, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    enhanced = cv2.createCLAHE(clipLimit=2, tileGridSize=(8, 8)).apply(aligned)
    ok, encoded = cv2.imencode('.png', enhanced)
    return encoded.tobytes() if ok else jpeg


def extract_lines(jpeg):
    prepared = prepare_text_image(jpeg)
    result = subprocess.run(
        ['tesseract', 'stdin', 'stdout', '-l', 'eng', '--dpi', '150', '--psm', '6', 'tsv'],
        input=prepared, check=True, capture_output=True, timeout=25,
    )
    lines = {}
    for row in csv.DictReader(io.StringIO(result.stdout.decode('utf-8')), delimiter='\t'):
        if row['level'] != '5' or not row['text'].strip():
            continue
        key = (row['block_num'], row['par_num'], row['line_num'])
        word = {'text': row['text'], 'confidence': float(row['conf']) / 100,
                'box': [int(row[field]) for field in ('left', 'top', 'width', 'height')]}
        lines.setdefault(key, []).append(word)
    return [{'text': ' '.join(word['text'] for word in words), 'words': words}
            for words in lines.values()]
