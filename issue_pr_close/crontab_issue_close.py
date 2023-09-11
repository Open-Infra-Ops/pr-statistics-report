# -*- coding: utf-8 -*-
# @Time    : 2023/8/25 14:54
# @Author  : Tom_zc
# @FileName: crontab_issue_close.py.py
# @Software: PyCharm
import copy
import datetime
import logging
import os
import smtplib
import textwrap
import time
from functools import wraps

import pytz
import requests
import yaml
import pandas as pd
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from logging import handlers
from requests.packages.urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

close_div_template = textwrap.dedent("""
    <div>
    <p>Dear,</p>
    <p>以下是MindSpore超期（{}天）状态未更新并且携带mindspore-assistant标签的ISSUE，请确认是否关闭：</p>
    <div class="table-detail">{}</div>
    </div>
""").strip()

notify_div_template = textwrap.dedent("""
    <div>
    <p>Dear,</p>
    <p>以下是MindSpore超3年状态未更新的ISSUE，请及时处理：</p>
    <div class="table-detail">{}</div>
    </div>
""").strip()

html_template = textwrap.dedent("""
<html>
<meta http-equiv="Content-Type" content="text/html;charset=UTF-8"/>
<head>
    <title>MindSpore</title>
    <style>

        table {
            border-collapse: collapse
        }

        th, td {
            border: 1px solid #000
        }

        .table-detail {
            left: 20px;
            bottom: 20px
        }
    </style>
</head>
<body>
{{template}}
</body>
</html>
""").strip()

close_issue_comment = """您好，由于问题单没有回复，我们后续会关闭，如您仍有疑问，可以反馈下具体信息，并将ISSUE状态修改为WIP，我们这边会进一步跟踪，谢谢"""


class Logger:
    level_relations = {
        'debug': logging.DEBUG,
        'info': logging.INFO,
        'warning': logging.WARNING,
        'error': logging.ERROR,
        'crit': logging.CRITICAL
    }

    def __init__(self, filename, level='info', when='D', back_count=3,
                 fmt='%(asctime)s - %(pathname)s[line:%(lineno)d] - %(levelname)s: %(message)s'):
        self.logger = logging.getLogger(filename)
        format_str = logging.Formatter(fmt)
        self.logger.setLevel(self.level_relations.get(level))
        sh = logging.StreamHandler()
        sh.setFormatter(format_str)
        th = handlers.TimedRotatingFileHandler(filename=filename, when=when, backupCount=back_count, encoding='utf-8')
        th.setFormatter(format_str)
        self.logger.addHandler(sh)
        self.logger.addHandler(th)


cur_file_name = "{}.log".format(os.path.basename(__file__).split(".")[0])
logger = Logger(cur_file_name, level='info').logger


def func_retry(retry=3, delay=1):
    def deco_retry(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            for i in range(retry):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    logger.error("[func_retry] e:{}, args:{}, kwargs:{}".format(e, args, kwargs))
                    time.sleep(delay)
            else:
                logger.error("[func_retry] retry reached the number of failures")
                return list()

        return inner

    return deco_retry


class EmailImplement(object):
    def __init__(self, email_host, email_port, email_username, email_pwd):
        self.server = smtplib.SMTP(email_host, int(email_port))
        self.server.ehlo()
        self.server.starttls()
        self.server.login(email_username, email_pwd)

    @func_retry(retry=5)
    def send_email(self, email_from, email_receivers, subject, body_of_email):
        if not isinstance(email_receivers, list):
            email_receivers = [email_receivers, ]
        content = MIMEText(body_of_email, 'html', 'utf-8')
        msg = MIMEMultipart()
        msg.attach(content)
        msg['Subject'] = subject
        msg['From'] = email_from
        msg['To'] = ",".join(email_receivers)
        self.server.sendmail(email_from, email_receivers, msg.as_string())
        logger.info('Success sent report email to: {}'.format(msg['To']))


class GiteeRequest:
    request_open_issue_url = "https://gitee.com/api/v5/enterprises/mind_spore/issues?access_token={}&state=open&sort=created&direction=desc&page={}&per_page=100"
    request_progressing_issue_url = "https://gitee.com/api/v5/enterprises/mind_spore/issues?access_token={}&state=progressing&sort=created&direction=desc&page={}&per_page=100"
    request_issue_comments_url = "{}?access_token={}&page={}&per_page=100"
    request_close_issue_url = "https://gitee.com/api/v5/enterprises/mind_spore/issues/{}"
    request_issue_label_url = "https://gitee.com/api/v5/enterprises/mind_spore/issues/{}/labels?access_token={}&page={}&per_page=100"
    request_comment_issue_url = "https://gitee.com/api/v5/repos/{}/{}/issues/{}/comments"

    def __init__(self, token):
        self.token = token
        self.hearder = {
            "Content-Type": "application/json",
            "charset": "UTF-8"
        }
        self.verify = True

    @func_retry()
    def request_open_issue(self, page):
        url = self.request_open_issue_url.format(self.token, page)
        resp = requests.get(url=url, headers=self.hearder, verify=self.verify, timeout=(300, 300))
        if not str(resp.status_code).startswith("2"):
            raise Exception("[request_open_issue] request return code:{}".format(resp.status_code))
        return resp.json()

    @func_retry()
    def request_progressing_issue(self, page):
        url = self.request_progressing_issue_url.format(self.token, page)
        resp = requests.get(url=url, headers=self.hearder, verify=self.verify, timeout=(300, 300))
        if not str(resp.status_code).startswith("2"):
            raise Exception("[request_progressing_issue_url] request return code:{}".format(resp.status_code))
        return resp.json()

    @func_retry()
    def requst_issue_comments(self, url, page):
        url = self.request_issue_comments_url.format(url, self.token, page)
        resp = requests.get(url, headers=self.hearder, verify=self.verify, timeout=(300, 300))
        if not str(resp.status_code).startswith("2"):
            raise Exception("[requst_issue_comments] request return code:{}".format(resp.status_code))
        return resp.json()

    @func_retry()
    def request_close_issue(self, issue_id):
        url = self.request_close_issue_url.format(issue_id)
        body = {"access_token": self.token, "state": "closed"}
        resp = requests.patch(url=url, headers=self.hearder, json=body, verify=self.verify, timeout=(300, 300))
        if not str(resp.status_code).startswith("2"):
            raise Exception(
                "[request_close_issue] request return code:{}".format(resp.status_code))
        return resp.json()

    @func_retry()
    def request_issue_label(self, issue_id, page):
        url = self.request_issue_label_url.format(issue_id, self.token, page, timeout=(300, 300))
        resp = requests.get(url, headers=self.hearder, verify=self.verify)
        if not str(resp.status_code).startswith("2"):
            raise Exception(
                "[request_issue_label] request return code:{}".format(resp.status_code))
        return resp.json()

    @func_retry()
    def request_comment_issue(self, org, repo, issue_id, comment=close_issue_comment):
        url = self.request_comment_issue_url.format(org, repo, issue_id)
        body = {"access_token": self.token, "body": comment}
        resp = requests.post(url=url, headers=self.hearder, json=body, verify=self.verify, timeout=(300, 300))
        if not str(resp.status_code).startswith("2"):
            raise Exception(
                "[request_close_issue] request return code:{}".format(resp.status_code))
        return resp.json()


def parse_all_issue(issue_list):
    list_parsed_issue = list()
    stantard_project_set = {"MindSpore REQ Tracking System", "MindSpore Iteration Management", "MindSpore Bug Tracking System"}
    stantard_project_set_len = len(stantard_project_set)
    close_status_list = ["closed", "rejected", "done"]
    for issue in issue_list:
        project_list = list()
        if issue.get("program"):
            project_list.append(issue["program"]["name"].strip())
        if issue.get("programs"):
            programs = [i["name"].strip() for i in issue["programs"]]
            project_list.extend(programs)
        if len(stantard_project_set - set(project_list)) != stantard_project_set_len:
            logger.error("[parse_all_issue] find invalid object:{},{}".format(project_list, issue["html_url"]))
            continue
        if issue["state"].lower() not in close_status_list and issue.get("issue_state", "").lower() not in close_status_list:
            dict_issue = dict()
            responsible_list = list()
            list_status = list()
            if issue.get("assignee"):
                responsible_list.append(issue["assignee"]["name"])
            if issue.get("collaborators"):
                responsible_list.extend([i["name"] for i in issue["collaborators"]])
            if issue["state"].lower():
                list_status.append(issue["state"])
            if issue.get("issue_state", "").lower():
                list_status.append(issue["issue_state"])
            dict_issue["issue_id"] = issue["number"]
            dict_issue["responsible"] = "，".join(responsible_list)
            dict_issue["orgination"] = issue["repository"]["namespace"]["name"] if issue.get("repository") else None
            dict_issue["repo"] = issue["repository"]["name"] if issue.get("repository") else None
            dict_issue["html_url"] = issue["html_url"]
            dict_issue["created_at"] = issue["created_at"]
            dict_issue["comments_url"] = issue["comments_url"]
            dict_issue["title"] = issue["title"]
            dict_issue["project_list"] = ",".join(project_list)
            dict_issue["status"] = ",".join(list_status)
            list_parsed_issue.append(dict_issue)
    return list_parsed_issue


def get_open_issue(token):
    gitee_request = GiteeRequest(token)
    all_list_issue = list()
    page = 0
    while True:
        limit_issue = gitee_request.request_open_issue(page)
        logger.info("collect open issue:{}".format(len(limit_issue)))
        parse_issue = parse_all_issue(limit_issue)
        all_list_issue.extend(parse_issue)
        if len(limit_issue) == 100:
            page += 1
            continue
        break
    return all_list_issue


def get_progressing_issue(token):
    gitee_request = GiteeRequest(token)
    all_list_issue = list()
    page = 0
    while True:
        limit_issue = gitee_request.request_progressing_issue(page)
        logger.info("collect progressing issue:{}".format(len(limit_issue)))
        parse_issue = parse_all_issue(limit_issue)
        all_list_issue.extend(parse_issue)
        if len(limit_issue) == 100:
            page += 1
            continue
        break
    return all_list_issue


def get_comment_max_date(token, url, issue_create_date):
    gitee_request = GiteeRequest(token)
    list_comment = list()
    page = 0
    while True:
        comments = gitee_request.requst_issue_comments(url, page)
        comments = [datetime.datetime.strptime(comment["created_at"], "%Y-%m-%dT%H:%M:%S+08:00")
                    for comment in comments]
        list_comment.extend(comments)
        if len(comments) == 100:
            page += 1
            continue
        break
    logger.info("collect comment:{}".format(len(list_comment)))
    if len(list_comment):
        max_date = max(list_comment)
    else:
        max_date = datetime.datetime.strptime(issue_create_date, "%Y-%m-%dT%H:%M:%S+08:00")
    return max_date


def get_issue_label(token, issue_id):
    gitee_request = GiteeRequest(token)
    list_labels = list()
    page = 0
    while True:
        labels = gitee_request.request_issue_label(issue_id, page)
        logger.info("collect labels:{}".format(len(labels)))
        label_names = [label["name"].lower() for label in labels]
        list_labels.extend(label_names)
        if len(labels) == 100:
            page += 1
            continue
        break
    return list_labels


# noinspection PyShadowingNames
def get_need_close_and_notify_issue(token, close_day, notify_day, issue_list):
    tzinfo = pytz.timezone('Asia/Shanghai')
    cur = datetime.datetime.now(tz=tzinfo)
    logger.info("collect time:{}".format(cur))
    close_issue_list, notify_issue_list = list(), list()
    for issue in issue_list:
        max_date = get_comment_max_date(token, issue["comments_url"], issue["created_at"])
        if cur < tzinfo.localize(max_date) + datetime.timedelta(days=close_day):
            continue
        assistant_label = "mindspore-assistant"
        all_label = get_issue_label(token, issue["issue_id"])
        new_issue = copy.deepcopy(issue)
        new_issue["label"] = ",".join(all_label)
        # 1.标签带有mindspore-assistant，14天，邮件通知，不关闭
        # 2.其他情况，超期3年，邮件通知，不关闭
        if assistant_label.lower() in all_label:
            close_issue_list.append(new_issue)
        elif cur >= tzinfo.localize(max_date) + datetime.timedelta(days=notify_day):
            notify_issue_list.append(new_issue)
    return close_issue_list, notify_issue_list


def close_issue(token, need_close_issues):
    gitee_request = GiteeRequest(token)
    list_exist_id = list()
    for issue in need_close_issues:
        if issue["orgination"] and issue["repo"]:
            issue_id = issue["issue_id"]
            if issue_id in list_exist_id:
                continue
            else:
                list_exist_id.append(issue_id)
            # comment
            gitee_request.request_comment_issue(issue["orgination"], issue["repo"], issue["issue_id"])
            # close
            # gitee_request.request_close_issue(issue["issue_id"])
        else:
            logger.info("[close_issue] issue is not bound to org or repo")


def pandas_clean(need_close_issues, is_close=False, is_status=False):
    list_data = list()
    list_exist_id = list()
    for issue in need_close_issues:
        issue_id = issue["issue_id"]
        if issue_id in list_exist_id:
            continue
        else:
            list_exist_id.append(issue_id)
        dict_data = dict()
        dict_data["ID"] = issue_id
        dict_data["仓库"] = issue["repo"]
        dict_data["标题"] = "<a href='{0}'>{1}</a>".format(issue["html_url"], issue["title"])
        dict_data["责任人"] = issue["responsible"]
        if is_status:
            dict_data["状态"] = issue["status"]
        if is_close:
            dict_data["项目名称"] = issue["project_list"]
        dict_data["标签"] = issue["label"]
        dict_data["创建时间"] = issue["created_at"].split("T")[0]
        list_data.append(dict_data)
    sort_list = sorted(list_data, key=lambda x: x["创建时间"], reverse=True)
    return sort_list


# noinspection PyTypeChecker
@func_retry()
def close_issue_email_notify(config_dict, close_day, need_close_issues):
    cleaned_info = pandas_clean(need_close_issues, is_close=True)
    pd.set_option('display.width', 800)
    pd.set_option('colheader_justify', 'center')
    pd.options.display.html.border = 2
    df = pd.DataFrame.from_dict(cleaned_info)
    df_style = df.style.hide_index()
    html = df_style.render()
    content = close_div_template.format(str(close_day), html)
    template_content = html_template.replace(r"{{template}}", content)
    if os.getenv("debug", True):
        with open("./close.html", "w", encoding="utf-8") as f:
            f.write(template_content)
    email_host = config_dict["email_host"]
    email_port = config_dict["email_port"]
    email_username = config_dict["email_username"]
    email_pwd = config_dict["email_pwd"]
    email_from = config_dict["close_email_from"]
    email_receive = [i.strip() for i in config_dict["close_email_receive"].split(",")]
    email_subject = 'Mindspore超期并携带mindspore-assistant标签待关闭ISSUE'
    email_impl = EmailImplement(email_host, email_port, email_username, email_pwd)
    email_impl.send_email(email_from, email_receive, email_subject, template_content)


# noinspection PyTypeChecker
def notify_issue_email_notify(config_dict, need_notfiy_issues):
    cleaned_info = pandas_clean(need_notfiy_issues, is_status=True)
    pd.set_option('display.width', 800)
    pd.set_option('display.max_colwidth', 150)
    pd.set_option('colheader_justify', 'center')
    pd.options.display.html.border = 2
    df = pd.DataFrame.from_dict(cleaned_info)
    df_style = df.style.hide_index()
    html = df_style.render()
    content = notify_div_template.format(html)
    template_content = html_template.replace(r"{{template}}", content)
    if os.getenv("debug", True):
        with open("./notify.html", "w", encoding="utf-8") as f:
            f.write(template_content)
    email_host = config_dict["email_host"]
    email_port = config_dict["email_port"]
    email_username = config_dict["email_username"]
    email_pwd = config_dict["email_pwd"]
    email_from = config_dict["notify_email_from"]
    email_receive = [i.strip() for i in config_dict["notify_email_receive"].split(",")]
    email_subject = '超3年无状态更新ISSUE提醒'
    email_impl = EmailImplement(email_host, email_port, email_username, email_pwd)
    email_impl.send_email(email_from, email_receive, email_subject, template_content)


def read_config(config_path):
    with open(config_path, "r", encoding="utf-8") as f:
        content = yaml.load(f, Loader=yaml.FullLoader)
    return content


def rm_file(config_path):
    if os.path.exists(config_path):
        os.remove(config_path)


def parse_config(config_dict):
    key = {"close_day", "notify_day", "gitee_token", "email_host", "email_port",
           "email_username", "email_pwd", "close_email_from", "close_email_receive",
           "notify_email_from", "notify_email_receive"}
    if set(config_dict.keys()) - key:
        raise RuntimeError("redundant parameter key")
    if key - set(config_dict.keys()):
        raise RuntimeError("missing parameter key")
    if int(config_dict["close_day"]) > int(config_dict["notify_day"]):
        raise RuntimeError("close_day must lt notify_day")
    if int(config_dict["close_day"]) <= 1:
        raise RuntimeError("close_day must ge 1")
    if int(config_dict["notify_day"]) <= 1:
        raise RuntimeError("notify_day must ge 1")


if __name__ == '__main__':
    tzinfo = pytz.timezone('Asia/Shanghai')
    _, which_month, which_days = datetime.datetime.now(tz=tzinfo).isocalendar()
    if which_month % 2 == 0 and which_days == 5:
        path = os.environ.get("crontab_issue_close_config", "crontab_issue_close.yaml")
        logger.info("*" * 25 + "1.parse config" + "*" * 25)
        config_content = read_config(path)
        rm_file(path)
        parse_config(config_content)
        gitee_token = config_content["gitee_token"]
        close_day = config_content["close_day"]
        notify_day = config_content["notify_day"]
        logger.info("*" * 25 + "2.get all issue" + "*" * 25)
        list_all_issue = get_open_issue(gitee_token)
        list_progressing_issue = get_progressing_issue(gitee_token)
        list_all_issue.extend(list_progressing_issue)
        logger.info("the all issue length:{}".format(len(list_all_issue)))
        logger.info("*" * 25 + "3.get the close and notify issue" + "*" * 25)
        close_issue_list, notify_issue_list = get_need_close_and_notify_issue(gitee_token, close_day, notify_day,
                                                                              list_all_issue)
        logger.info("*" * 25 + "4.close the close issue" + "*" * 25)
        close_issue(gitee_token, close_issue_list)
        logger.info("*" * 25 + "5.use email to notify the closed issue" + "*" * 25)
        close_issue_email_notify(config_content, close_day, close_issue_list)
        logger.info("*" * 25 + "6.use email to notify the notify issue" + "*" * 25)
        notify_issue_email_notify(config_content, notify_issue_list)
    else:
        print("The current execution time is a non-biweekly Friday:{}/{}".format(str(which_month), str(which_days)))
