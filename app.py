"""
@Author: Tianyi Zhang
@Date: 2024/9/13
@Description:
"""
from flask import Flask, request, send_file, render_template, redirect, url_for, send_from_directory, jsonify
from urllib.parse import quote, unquote

import requests
from datetime import datetime
from bs4 import BeautifulSoup
import socket
import os

app = Flask(__name__)

BASE_URL = 'http://app.buaa.edu.cn/'
LOGIN_URL = 'https://sso.buaa.edu.cn/login'


# Helper functions from your script
def get_login_token(session):
    r = session.get(
        "https://sso.buaa.edu.cn/login?service=https%3A%2F%2Fapp.buaa.edu.cn%2Fa_buaa%2Fapi%2Fcas%2Findex%3Fredirect%3D%252Fsite%252Fcenter%252Fpersonal%26from%3Dwap%26login_from%3D&noAutoRedirect=1")
    soup = BeautifulSoup(r.content, 'html.parser')
    return soup.find('input', {'name': 'execution'})['value']


def login(session, username, password):
    formdata = {
        'username': username,
        'password': password,
        'execution': get_login_token(session),
        'type': 'username_password',
        '_eventId': 'submit',
        'submit': '登录'
    }
    r = session.post(LOGIN_URL, data=formdata, allow_redirects=False)
    location = r.headers.get('Location')
    if location:
        return location
    else:
        return None


def get_eai_sess():
    url = 'https://app.buaa.edu.cn/uc/wap/login'
    r = requests.get(url, allow_redirects=False)
    cookies = requests.utils.dict_from_cookiejar(r.cookies)
    return cookies["eai-sess"]


def verify_eai_sess(username, password):
    session = requests.session()
    url = login(session, username, password)
    if url is None:
        return None
    eai_sess = get_eai_sess()
    hearders = {
        'cookie': eai_sess
    }
    r = requests.get(url,headers=hearders,allow_redirects=False)
    cookies = requests.utils.dict_from_cookiejar(r.cookies)
    date = r.headers.get('date')
    if date:
        return cookies["eai-sess"]
    else:
        return None


def merge_adjacent_classes(classes):
    i = 1
    while i < len(classes):
        if classes[i]["course_name"] == classes[i - 1]["course_name"]:
            classes[i - 1]["lessons"] += f'{classes[i]["lessons"]}'
            classes[i - 1][
                "course_time"] = f'{classes[i - 1]["course_time"].split("～")[0]}～{classes[i]["course_time"].split("～")[1]}'
            classes.pop(i)
        else:
            i += 1
    return classes

def get_public_ip():
    try:
        response = requests.get("https://ifconfig.me")
        ip = response.text.strip()
        return ip
    except Exception as e:
        return "127.0.0.1"


def get_class_by_week(year: str, term: str, week: str, eai_sess: str) -> list[dict]:
    class_url = "https://app.buaa.edu.cn/timetable/wap/default/get-datatmp"
    header = {
        "Cookie": f"eai-sess={eai_sess}",
    }
    data = {
        "year": year,
        "term": term,
        "week": week,
        "type": "1",
    }

    # 发送请求并处理响应
    r = requests.post(class_url, data=data, headers=header)
    if r.status_code != 200:
        print(f"Error: Unable to fetch data, status code {r.status_code}")
        return []

    response_json = r.json()

    if "d" not in response_json or "weekdays" not in response_json["d"] or "classes" not in response_json["d"]:
        print("Error: Invalid response structure")
        return []

    days = response_json["d"]["weekdays"]
    classes = response_json["d"]["classes"]

    # 按星期几和课程节次排序
    classes = merge_adjacent_classes(sorted(
        classes, key=lambda klass: int(klass["weekday"]) * 100 + int(klass["lessons"][0:1])
    ))

    for klass in classes:
        # 将日期处理为 YYYYMMDD 格式
        klass["date"] = days[int(klass["weekday"]) - 1].replace("-", "")

        # 确保处理 course_time 字段并进行拆分
        if "course_time" in klass and klass["course_time"]:  # 确保字段存在且不为空
            course_time_split = klass["course_time"].split("-")
            klass["start"] = course_time_split[0].replace(":", "")
            if len(course_time_split) > 1:  # 检查是否有结束时间
                klass["end"] = course_time_split[1].replace(":", "")
            else:
                klass["end"] = klass["start"]  # 设置默认值，如果只有起始时间则结束时间等于起始时间
        else:
            # 处理 course_time 字段不存在或为空的情况
            print(f'Warning: course_time not exists for course {klass["course_name"]}')
            klass["start"] = "000000"  # 默认开始时间，作为占位符
            klass["end"] = "000000"  # 默认结束时间，作为占位符

        # 格式化 lessons 字段
        klass["lessons"] = ", ".join([klass["lessons"][i:i + 2] for i in range(0, len(klass["lessons"]), 2)])

    return classes


def generate_ics(title, classes, trigger):
    ics_payload = f"""BEGIN:VCALENDAR
VERSION:2.0
X-WR-CALNAME:{title}
CALSCALE:GREGORIAN
BEGIN:VTIMEZONE
TZID:Asia/Shanghai
TZURL:http://tzurl.org/zoneinfo-outlook/Asia/Shanghai
X-LIC-LOCATION:Asia/Shanghai
BEGIN:STANDARD
TZOFFSETFROM:+0800
TZOFFSETTO:+0800
TZNAME:CST
DTSTART:19700101T000000
END:STANDARD
END:VTIMEZONE"""

    for klass in classes:
        # 确保时间格式正确，补齐时间为 HHMMSS 格式
        start_time = klass["start"].ljust(6, "0")  # 确保是 6 位，HHMMSS
        end_time = klass["end"].ljust(6, "0")      # 确保是 6 位，HHMMSS

        event_start = f'{klass["date"]}T{start_time}'
        event_end = f'{klass["date"]}T{end_time}'

        # 替换多行文本中的换行符并进行转义
        event_description = f"""编号：{klass["course_id"]}
名称：{klass["course_name"]}
教师：{klass["teacher"]}
学分：{klass["credit"]}
类型：{klass["course_type"]}
课时：{klass["course_hour"]}
上课时间：{klass["course_time"]}；第 {klass["lessons"]} 节""".replace("\n", "\\n")

        # 创建每个VEVENT块，确保时间格式和ICS字段格式正确
        event_info = f"""
BEGIN:VEVENT
DESCRIPTION:{event_description}
DTSTART;TZID=Asia/Shanghai:{event_start}
DTEND;TZID=Asia/Shanghai:{event_end}
LOCATION:{klass["location"]}
SUMMARY:{klass["course_name"]}
BEGIN:VALARM
TRIGGER:-PT{trigger}M
REPEAT:1
DURATION:PT1M
END:VALARM
END:VEVENT"""
        ics_payload += event_info

    # 结束日历文件
    ics_payload += "\nEND:VCALENDAR"

    return ics_payload



def current_date_str():
    return datetime.now().strftime("%Y-%m-%d")

# Helper function to check if file is less than 7 days old
def is_file_recent(filename):
    if os.path.exists(filename):
        file_time = datetime.fromtimestamp(os.path.getmtime(filename))
        return (datetime.now() - file_time).days <= 7
    return False

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/seed', methods=['GET'])
def seed():
    username = request.args.get('username')
    encoded_password = request.args.get('password')
    trigger = request.args.get('trigger', '30')

    password = unquote(encoded_password)

    if not username or not password:
        return "Missing username or password", 400

    # Define the ics filename based on the username and date
    ics_filename = f"{username}_{current_date_str()}.ics"
    # Check if the ICS file exists and is recent (within 7 days)
    if is_file_recent(ics_filename):
        return send_file(ics_filename, as_attachment=True)
    else:
        # If the file doesn't exist or is too old, redirect to /generate_link to regenerate
        return redirect(url_for('generate_link', username=username, password=encoded_password, trigger=trigger))


# Handle form input and generate link
@app.route('/generate_link', methods=['POST', 'GET'])
def generate_link():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        trigger = request.form.get('trigger', '30')
    else:
        username = request.args.get('username')
        password = request.args.get('password')
        trigger = request.args.get('trigger', '30')

    # 将密码和其他输入URL编码
    encoded_password = quote(password)

    # Define the ics filename based on the username and current date
    ics_filename = f"{username}_{current_date_str()}.ics"
    config_filename = f"{username}.config"

    # Step 1: Verify login and get session
    eai_sess = verify_eai_sess(username, password)
    if not eai_sess:
        reminder_message = "登陆失败,请检查您的学号和密码"
        return jsonify({'error': '登陆失败，请检查您的学号和密码'}), 401

    # Step 2: Get current academic year and term
    year = datetime.now().year
    month = datetime.now().month
    year_str = f"{year - 1}-{year}" if month < 7 else f"{year}-{year + 1}"
    term_str = "2" if month < 7 else "1"


    # Step 3: Collect class data for each week
    weekly_classes = []
    for week in range(1, 20):
        week_str = str(week)
        weekly_classes.extend(get_class_by_week(year_str, term_str, week_str, eai_sess))

    # Step 4: Generate the ICS file
    ics_content = generate_ics(f"北航 {year_str} 第 {term_str} 学期课程表", weekly_classes, trigger)

    # Step 5: Save the ICS file
    with open(ics_filename, 'w+', encoding='utf-8') as ics_file:
        ics_file.write(ics_content)

    # Step 6: Save the config file
    with open(config_filename, 'w+', encoding='utf-8') as config_file:
        config_file.write(f"username={username}\npassword={password}\ntrigger={trigger}\n")

    # Step 7: Construct the generated link
    domain = request.host
    generated_link = f"https://{domain}/seed?username={username}&password={encoded_password}&trigger={trigger}"

    # Return the generated link to the user
    return jsonify({'generated_link': generated_link})

if __name__ == '__main__':
    app.run(debug=True)
