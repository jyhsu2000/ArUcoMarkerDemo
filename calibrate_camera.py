#!/usr/bin/env python
import copy
import os.path
import re
import threading
import time
from collections import deque

import PySimpleGUI as sg
import cv2
import imutils
import pandas as pd
from PIL import Image, ImageTk, ImageOps

from utils import CameraLooper, eat_next_event, save_coefficients, Chessboard

calibration_images_path = './calibration_images'
thumbnail_size = (400, 300)

# 找棋盤格角點
# 設置尋找亞像素角點的參數，採用的停止準則是最大循環次數30和最大誤差容限0.001
criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)  # 阈值

# 預設棋盤格模板規格
default_chessboard = Chessboard(w=9, h=6, square_size_mm=24.6)


def update_calibration_image_df(window, calibration_image_df: pd.DataFrame) -> pd.DataFrame:
    # 取得檔案清單
    try:
        new_calibration_image_filenames = os.listdir(calibration_images_path)
    except:
        new_calibration_image_filenames = []
    new_calibration_image_df = pd.DataFrame({
        'filename': new_calibration_image_filenames,
        'chessboard': '',
    })
    # 與原有的合併
    calibration_image_df = pd.concat([calibration_image_df, new_calibration_image_df], axis='index')
    # 若重複，則以原有的為主
    calibration_image_df.drop_duplicates(subset=['filename'], keep='first', inplace=True)
    # 清除檔案不存在的
    calibration_image_df = calibration_image_df[calibration_image_df.filename.isin(new_calibration_image_filenames)]
    calibration_image_df.reset_index(drop=True, inplace=True)

    window['table'].update(values=calibration_image_df.values.tolist())

    return calibration_image_df


def detect_chessboard(window, chessboard: Chessboard, filename, image=None):
    if image is None:
        file_path = os.path.join(calibration_images_path, filename)
        image = cv2.imread(file_path)
    else:
        image = copy.deepcopy(image)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # 找到棋盤格角點
    ret, corners = cv2.findChessboardCorners(gray, (chessboard.w, chessboard.h), None)
    window.write_event_value('update_chessboard_detect_result', (filename, ret))
    if ret:
        # 在原角點的基礎上尋找亞像素角點
        cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
        # 追加進入世界三維點和平面二維點中
        # objpoints.append(objp)
        # imgpoints.append(corners)
        # 將角點在圖像上顯示
        cv2.drawChessboardCorners(image, (chessboard.w, chessboard.h), corners, ret)

    return ret, corners, image, gray,


def update_thumbnail_images(window, chessboard: Chessboard, filename: str):
    file_path = os.path.join(calibration_images_path, filename)
    image = cv2.imread(file_path)
    thumbnail_image = imutils.resize(image, width=thumbnail_size[0], height=thumbnail_size[1])
    window.write_event_value('update_thumbnail_image', thumbnail_image)

    ret, corners, image_with_marker, gray = detect_chessboard(window, chessboard, filename, image)
    thumbnail_image_with_marker = imutils.resize(image_with_marker, width=thumbnail_size[0], height=thumbnail_size[1])
    window.write_event_value('update_thumbnail_image_with_marker', thumbnail_image_with_marker)


def calibrate(window, chessboard: Chessboard, calibration_image_df: pd.DataFrame):
    row_count = len(calibration_image_df)

    # 儲存棋盤格角點的世界坐標和圖像坐標對
    obj_points = []  # 在世界坐標系中的三維點
    img_points = []  # 在圖像平面的二維點

    for idx, row in calibration_image_df.iterrows():
        window.write_event_value('update_progress', (idx + 1, row_count))
        ret, corners, image_with_marker, gray = detect_chessboard(window, chessboard, row['filename'])
        if ret:
            # 追加進入世界三維點和平面二維點中
            obj_points.append(chessboard.objp)
            img_points.append(corners)

    if len(img_points) == 0:
        window.write_event_value('calibrate_finished', 'No chessboard images found')
        return

    ret, camera_matrix, distortion_coefficients, rvecs, tvecs = cv2.calibrateCamera(obj_points, img_points, gray.shape[::-1], None, None)
    print('ret:', ret)
    print('camera_matrix:\n', camera_matrix)  # 內參數矩陣
    print('distortion_coefficients 畸變係數:\n', distortion_coefficients)  # 畸變係數   distortion coefficients = (k_1,k_2,p_1,p_2,k_3)
    print('rvecs 旋轉（向量）外參:\n', rvecs)  # 旋轉向量  # 外參數
    print('tvecs 平移（向量）外參:\n', tvecs)  # 平移向量  # 外參數
    # 儲存參數
    save_coefficients(camera_matrix, distortion_coefficients)

    window.write_event_value('calibrate_finished', 'Calibration finished.\nCoefficients saved to camera.yml')


def main():
    resize_size = 720
    chessboard = copy.deepcopy(default_chessboard)

    calibration_image_df = pd.DataFrame({
        'filename': [],
        'chessboard': '',
    })

    sg.theme('DefaultNoMoreNagging')

    layout = [
        [sg.Text('CalibrateCamera', size=(40, 1), justification='center', font='Helvetica 20', expand_x=True)],
        [
            sg.Column([
                [sg.Table(
                    values=calibration_image_df.values.tolist(),
                    headings=calibration_image_df.columns.tolist(),
                    auto_size_columns=False,
                    display_row_numbers=True,
                    justification='left',
                    col_widths=[30, 10],
                    num_rows=10,
                    key='table', expand_x=False, expand_y=False, enable_events=True
                )],
                [sg.Image(filename='', key='thumbnail', size=(400, 1))],
                [sg.Image(filename='', key='thumbnail_with_marker', size=(400, 1))],
                [sg.Button('Delete selected image', key='delete_selected_image', enable_events=True, button_color=('white', 'red'), font='Helvetica 14', expand_x=True, disabled=True)],
                [
                    sg.Text('Chessboard size (w*h):', size=(20, 1), font='Helvetica 14', justification='right'),
                    sg.InputText(key='w_input', size=(4, 1), font='Helvetica 14', justification='center', enable_events=True, default_text=default_chessboard.w),
                    sg.Text('x', font='Helvetica 14', justification='center'),
                    sg.InputText(key='h_input', size=(4, 1), font='Helvetica 14', justification='center', enable_events=True, default_text=default_chessboard.h),
                ], [
                    sg.Text('Square size (mm):', size=(20, 1), font='Helvetica 14', justification='right'),
                    sg.InputText(key='square_size_input', size=(10, 1), font='Helvetica 14', justification='center', enable_events=True, default_text=default_chessboard.square_size_mm),
                ],
                [
                    sg.Button('Calibrate', key='calibrate', font='Helvetica 20', enable_events=True),
                    sg.ProgressBar(max_value=10, orientation='h', size=(20, 20), key='progress'),
                ],
            ], expand_y=True),
            sg.Image(filename='', key='image', right_click_menu=['', ['Original size', 'Resize to 360', 'Resize to 480', 'Resize to 720', 'Resize to 1080']]),
        ],
        [
            sg.Text('', key='capture_fps', size=(15, 1), justification='center', font='Helvetica 20'),
            sg.Text('', key='process_fps', size=(15, 1), justification='center', font='Helvetica 20'),
            sg.Column([
                [sg.Button('Capture', key='capture', font='Helvetica 20', enable_events=True)],
            ], element_justification='right', expand_x=True),
        ],
    ]

    window = sg.Window('CalibrateCamera', layout, location=(100, 100))

    camera_looper = CameraLooper()

    window.finalize()
    calibration_image_df = update_calibration_image_df(window, calibration_image_df)

    recent_frame_count = 10
    recent_frame_time = deque([0.0], maxlen=recent_frame_count)

    try:
        while True:
            event, values = window.read(timeout=0)
            if event == sg.WIN_CLOSED:
                break

            if event == 'table':
                try:
                    selected_row_index = values["table"][0]
                except IndexError:
                    selected_row_index = None
                if selected_row_index is not None:
                    selected_filename = calibration_image_df.loc[selected_row_index, 'filename']
                    thread = threading.Thread(target=update_thumbnail_images, args=(window, chessboard, selected_filename), daemon=True)
                    thread.start()
                    window['delete_selected_image'].update(disabled=False)
                else:
                    window['thumbnail'].update(source=None)
                    window['thumbnail_with_marker'].update(source=None)
                    window['delete_selected_image'].update(disabled=True)

            if event == 'update_chessboard_detect_result':
                filename, ret = values['update_chessboard_detect_result']
                calibration_image_df.loc[calibration_image_df.filename == filename, 'chessboard'] = ret
                window['table'].update(values=calibration_image_df.values.tolist())
                try:
                    selected_row_index = values["table"][0]
                except:
                    selected_row_index = None
                if selected_row_index is not None:
                    window['table'].update(select_rows=[selected_row_index])  # 似乎會自動觸發事件（似乎被認定為 Bug）
                    eat_next_event(window, 'table')  # 消除前述錯誤觸發的事件

            if event == 'update_thumbnail_image':
                thumbnail_image = values['update_thumbnail_image']
                window['thumbnail'].update(data=ImageTk.PhotoImage(image=Image.fromarray(thumbnail_image[:, :, ::-1])))

            if event == 'update_thumbnail_image_with_marker':
                thumbnail_image_with_marker = values['update_thumbnail_image_with_marker']
                window['thumbnail_with_marker'].update(data=ImageTk.PhotoImage(image=Image.fromarray(thumbnail_image_with_marker[:, :, ::-1])))

            if event == 'delete_selected_image':
                selected_row_index = values["table"][0]
                selected_filename = calibration_image_df.loc[selected_row_index, 'filename']
                file_path = os.path.join(calibration_images_path, selected_filename)
                os.remove(file_path)
                calibration_image_df = update_calibration_image_df(window, calibration_image_df)
                window.write_event_value('table', [None])

            if event == 'w_input':
                w_input = values['w_input']
                if len(w_input) > 2:
                    w_input = w_input[:2]
                else:
                    if re.match(r'^\d*$', w_input):
                        if re.match(r'^\d+$', w_input):
                            chessboard.w = int(w_input)
                    else:
                        w_input = chessboard.w
                window['w_input'].update(w_input)

            if event == 'h_input':
                h_input = values['h_input']
                if len(h_input) > 2:
                    h_input = h_input[:2]
                else:
                    if re.match(r'^\d*$', h_input):
                        if re.match(r'^\d+$', h_input):
                            chessboard.h = int(h_input)
                    else:
                        h_input = chessboard.h
                window['h_input'].update(h_input)

            if event == 'square_size_input':
                square_size_input = values['square_size_input']
                if len(square_size_input) > 7:
                    square_size_input = square_size_input[:7]
                else:
                    if re.match(r'^\d*\.?\d*$', square_size_input):
                        if re.match(r'^\d+\.?\d*$', square_size_input):
                            chessboard.square_size_mm = float(square_size_input)
                    else:
                        square_size_input = chessboard.square_size_mm
                window['square_size_input'].update(square_size_input)

            if event == 'calibrate':
                window['w_input'].update(chessboard.w, disabled=True)
                window['h_input'].update(chessboard.h, disabled=True)
                window['square_size_input'].update(chessboard.square_size_mm, disabled=True)
                window['calibrate'].update(disabled=True)
                thread = threading.Thread(target=calibrate, args=(window, chessboard, calibration_image_df), daemon=True)
                thread.start()

            if event == 'calibrate_finished':
                window['progress'].update_bar(1, max=1)
                custom_message = values['calibrate_finished']
                sg.popup(custom_message)
                window['w_input'].update(disabled=False)
                window['h_input'].update(disabled=False)
                window['square_size_input'].update(disabled=False)
                window['calibrate'].update(disabled=False)

            if event == 'update_progress':
                current_count, max_value = values['update_progress']
                window['progress'].update_bar(current_count, max=max_value)

            if event == 'Original size':
                resize_size = None
            if event.startswith('Resize to '):
                resize_size = int(event.split(' ')[-1])

            ret, frame = camera_looper.read()
            if not ret:
                continue

            if event == 'capture':
                filename = time.strftime('%Y%m%d_%H%M%S', time.localtime()) + '.jpg'
                file_path = os.path.join(calibration_images_path, filename)
                if not os.path.exists(os.path.dirname(file_path)):
                    os.makedirs(os.path.dirname(file_path))
                cv2.imwrite(file_path, frame)

                # Update file list
                calibration_image_df = update_calibration_image_df(window, calibration_image_df)
                selected_index = calibration_image_df.filename.eq(filename).idxmax()
                window['table'].update(select_rows=[selected_index])  # 似乎會自動觸發事件（似乎被認定為 Bug）
                window['table'].Widget.see(selected_index + 1)
                eat_next_event(window, 'table')  # 消除前述錯誤觸發的事件
                window.write_event_value('table', [selected_index])

            # img_bytes = cv2.imencode('.png', frame)[1].tobytes()
            image = Image.fromarray(frame[:, :, ::-1])
            if resize_size:
                image = ImageOps.contain(image, (resize_size, resize_size))
            img_bytes = ImageTk.PhotoImage(image=image)
            window['image'].update(data=img_bytes)
            window['capture_fps'].update(f'Capture: {camera_looper.fps:.1f} fps')

            new_frame_time = time.time()
            show_fps = 1 / ((new_frame_time - recent_frame_time[0]) / recent_frame_count)
            recent_frame_time.append(new_frame_time)
            window['process_fps'].update(f'Process: {show_fps:.1f} fps')
    finally:
        camera_looper.stop()
        window.close()


if __name__ == '__main__':
    main()
