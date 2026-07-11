import cv2
import numpy as np
import os

input_dir = "output"
output_dir = "output_clear"
os.makedirs(output_dir, exist_ok=True)

for filename in os.listdir(input_dir):
    if filename.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff')):
        input_image = os.path.join(input_dir, filename)
        img = cv2.imread(input_image)
        if img is None:
            continue
        # 1. 灰度
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # 2. CLAHE 局部对比度增强
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)
        # 3. 去噪
        gray = cv2.fastNlMeansDenoising(gray, h=10)
        # 4. 锐化
        blur = cv2.GaussianBlur(gray, (0, 0), sigmaX=50.0)
        sharpen = cv2.addWeighted(gray, 1.5, blur, -0.5, 0)
        # 保存
        output_image = os.path.join(output_dir, filename)
        cv2.imwrite(output_image, sharpen)