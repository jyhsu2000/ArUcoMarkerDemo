#!/usr/bin/env python
import copy
import os.path
import threading
import time
from collections import deque

import PySimpleGUI as sg
import cv2
import imutils
import numpy as np
import pandas as pd
from PIL import Image, ImageTk

from utils import CameraLooper, eat_next_event

calibration_images_path = './calibration_images'
thumbnail_size = (400, 300)

# 找棋盤格角點
# 設置尋找亞像素角點的參數，採用的停止準則是最大循環次數30和最大誤差容限0.001
criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)  # 阈值
# 棋盤格模板規格
w = 9  # 10 - 1
h = 6  # 7  - 1
# 世界坐標系中的棋盤格點,例如(0,0,0), (1,0,0), (2,0,0) ....,(8,5,0)，去掉Z坐標，記為二維矩陣
objp = np.zeros((w * h, 3), np.float32)
objp[:, :2] = np.mgrid[0:w, 0:h].T.reshape(-1, 2)
objp = objp * 18.1  # 18.1 mm


def reload_calibration_image_df(window):
    # FIXME: 會錯誤清除已存在的 chessboard 欄位資料
    calibration_image_filenames = os.listdir(calibration_images_path)
    calibration_image_df = pd.DataFrame({
        'filename': calibration_image_filenames,
        'chessboard': '',
    })
    window['table'].update(values=calibration_image_df.values.tolist())

    return calibration_image_df


def update_thumbnail_images(window, filename: str):
    file_path = os.path.join(calibration_images_path, filename)
    image = cv2.imread(file_path)
    thumbnail_image = imutils.resize(image, width=thumbnail_size[0], height=thumbnail_size[1])
    window.write_event_value('update_thumbnail_image', thumbnail_image)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    # 找到棋盤格角點
    ret, corners = cv2.findChessboardCorners(gray, (w, h), None)
    window.write_event_value('update_chessboard_detect_result', (filename, ret))
    image_with_marker = copy.deepcopy(image)
    if ret:
        # 在原角點的基礎上尋找亞像素角點
        cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
        # 追加進入世界三維點和平面二維點中
        # objpoints.append(objp)
        # imgpoints.append(corners)
        # 將角點在圖像上顯示
        cv2.drawChessboardCorners(image_with_marker, (w, h), corners, ret)
    thumbnail_image_with_marker = imutils.resize(image_with_marker, width=thumbnail_size[0], height=thumbnail_size[1])
    window.write_event_value('update_thumbnail_image_with_marker', thumbnail_image_with_marker)


def main():
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
                [sg.Button('Delete selected image', key='delete_selected_image', enable_events=True, button_color=('white', 'red'), font='Helvetica 14', expand_x=True, disabled=True)]
            ], expand_y=True),
            sg.Image(filename='', key='image'),
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

    camera_looper = CameraLooper(window)

    window.finalize()
    calibration_image_df = reload_calibration_image_df(window)

    recent_frame_count = 10
    recent_frame_time = deque([0.0], maxlen=recent_frame_count)

    while True:
        event, values = window.read(timeout=0)
        if event == sg.WIN_CLOSED:
            return

        if event == 'table':
            print(f'{values["table"]=}')
            selected_row_index = values["table"][0]
            if selected_row_index is not None:
                selected_filename = calibration_image_df.loc[selected_row_index, 'filename']
                thread = threading.Thread(target=update_thumbnail_images, args=(window, selected_filename), daemon=True)
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
            calibration_image_df = reload_calibration_image_df(window)
            window.write_event_value('table', [None])

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
            calibration_image_df = reload_calibration_image_df(window)
            selected_index = calibration_image_df.filename.eq(filename).idxmax()
            window['table'].update(select_rows=[selected_index])  # 似乎會自動觸發事件（似乎被認定為 Bug）
            window['table'].Widget.see(selected_index + 1)
            eat_next_event(window, 'table')  # 消除前述錯誤觸發的事件
            window.write_event_value('table', [selected_index])

        # img_bytes = cv2.imencode('.png', frame)[1].tobytes()
        img_bytes = ImageTk.PhotoImage(image=Image.fromarray(frame[:, :, ::-1]))
        window['image'].update(data=img_bytes)
        window['capture_fps'].update(f'Capture: {camera_looper.fps:.1f} fps')

        new_frame_time = time.time()
        show_fps = 1 / ((new_frame_time - recent_frame_time[0]) / recent_frame_count)
        recent_frame_time.append(new_frame_time)
        window['process_fps'].update(f'Process: {show_fps:.1f} fps')


if __name__ == '__main__':
    main()
