"""
@Author: Tianyi Zhang
@Date: 2024/9/13
@Description:
"""
from flask import Flask, request, send_file, render_template, redirect, url_for, send_from_directory
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

    r = requests.post(class_url, data=data, headers=header)
    print(r.content)
    days = r.json()["d"]["weekdays"]
    classes = r.json()["d"]["classes"]
    classes = merge_adjacent_classes(sorted(classes, key=lambda klass: int(klass["weekday"]) * 100 + int(klass["lessons"][0:1])))

    for klass in classes:
        klass["date"] = days[int(klass["weekday"]) - 1].replace("-", "")
        if "course_time" in klass and klass["course_time"]:  # 确保字段存在且不为空
            course_time_split = klass["course_time"].split("～")
            klass["start"] = course_time_split[0].replace(":", "")
            if len(course_time_split) > 1:  # 检查是否有结束时间
                klass["end"] = course_time_split[1].replace(":", "")
            else:
                klass["end"] = klass["start"]  # 或根据需要设置一个默认或错误值
        else:
            # 处理course_time字段不存在或为空的情况，例如设置默认值或记录错误
            print('course_time not exists')
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
        # 处理时间格式，确保正确的时间格式并补全时间
        event_start = f'{klass["date"]}T{klass["start"].rjust(4, "0")}00'
        event_end = f'{klass["date"]}T{klass["end"].rjust(4, "0")}00'

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

    # Step 1: Verify login and get session
    eai_sess = verify_eai_sess(username, password)
    if not eai_sess:
        return "Login failed", 401

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
    ics_filename = f"{username}.ics"
    config_filename = f"{username}.config"

    # Step 5: Save the files
    with open(ics_filename, 'w+', encoding='utf-8') as ics_file:
        ics_file.write(ics_content)
    with open(config_filename, 'w+', encoding='utf-8') as config_file:
        config_file.write(f"username={username}\npassword={password}\ntrigger={trigger}\n")

    # Step 6: Return the ICS file as a download
    return send_file(ics_filename, as_attachment=True)

# 处理表单输入，生成链接
@app.route('/generate_link', methods=['POST'])
def generate_link():
    username = request.form.get('username')
    password = request.form.get('password')
    trigger = request.form.get('trigger', '30')

    # 将密码和其他输入URL编码
    from urllib.parse import quote
    encoded_password = quote(password)

    domain = request.host

    # 构造生成的URL
    generated_link = f"http://{domain}/seed?username={username}&password={encoded_password}&trigger={trigger}"

    return render_template('index.html', generated_link=generated_link)

if __name__ == '__main__':
    app.run(debug=True)
