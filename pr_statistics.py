# -*- coding: utf-8 -*-
import datetime
import logging
import os
import re
import shutil
import subprocess
import time
import traceback
import requests
import smtplib
import yaml
import textwrap
import pandas as pd
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from logging import handlers
from collections import defaultdict
from functools import wraps

div_template = textwrap.dedent("""
    <div>
    <p>Dear {},</p>
    <p>以下是您参与openGauss社区的SIG仓库下待处理的PR，烦请您及时跟进</p>
    <div class="table-detail">{}</div>
    </div>
""").strip()

html_template = textwrap.dedent("""
<html>
<meta http-equiv="Content-Type" content="text/html;charset=UTF-8"/>
<head>
    <title>openGauss</title>
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


class Logger(object):
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


logger = Logger('statistics.log', level='info').logger


class Config(object):
    gitee_token = os.getenv("access_token")
    pr_info_url = "https://gitee.com/api/v5/enterprise/opengaussorg/pull_requests?access_token={}&state=open&sort=created&direction=desc&page={}&per_page=100"
    email_host = os.getenv("host")
    email_port = os.getenv("port")
    email_user = os.getenv("user")
    email_pwd = os.getenv("pwd")
    email_from = os.getenv("from")
    debug = os.getenv("debug")
    html_template_file = "./template.html"
    char_split = "、"
    clone_dir = "/root/tc"
    clone_cmd = "cd /root && git clone https://gitee.com/opengauss/tc"
    gauss_relationship_path = "/root/tc/gauss_relationship.yaml"


class EmailImplement(object):
    def __init__(self):
        self.server = smtplib.SMTP(Config.email_host, int(Config.email_port))
        self.server.ehlo()
        self.server.starttls()
        self.server.login(Config.email_user, Config.email_pwd)

    def send_email(self, receivers, body_of_email):
        """send email"""
        if not isinstance(receivers, list):
            receivers = [receivers,]
        content = MIMEText(body_of_email, 'html', 'utf-8')
        msg = MIMEMultipart()
        msg.attach(content)
        msg['Subject'] = 'openGauss 待处理PR汇总'
        msg['From'] = Config.email_from
        msg['To'] = ",".join(receivers)
        try:
            self.server.sendmail(Config.email_from, receivers, msg.as_string())
            logger.info('Sent report email to: {}'.format(receivers))
        except smtplib.SMTPException as e:
            logger.error(e)


def execute_cmd(cmd, timeout=600):
    """execute cmd"""
    try:
        p = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE, shell=True, close_fds=True)
        t_wait_seconds = 0
        while True:
            if p.poll() is not None:
                break
            if timeout >= 0 and t_wait_seconds >= (timeout * 100):
                p.terminate()
                return -1, "", "execute_cmd exceeded time {0} seconds in executing: {1}".format(timeout, cmd)
            time.sleep(0.01)
            t_wait_seconds += 1
        out, err = p.communicate()
        ret = p.returncode
        return ret, out, err
    except Exception as e:
        return -1, "", "execute_cmd exceeded raise, e={0}, trace={1}".format(e.args[0], traceback.format_exc())


def func_retry(tries=5, delay=2):
    """the func retry decorator"""

    def deco_retry(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            for i in range(tries):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    logger.error("func_retry:{} e:{} traceback: {}".format(fn.__name__, e, traceback.format_exc()))
                    time.sleep(delay)
            else:
                logger.info("func_retry:{} over tries, failed".format(fn.__name__))
                raise RuntimeError("The func_retry over tries.Please check.")

        return inner

    return deco_retry


def calc_time(f):
    """get the speed of time"""

    def inner(*arg, **kwarg):
        s_time = time.time()
        res = f(*arg, **kwarg)
        e_time = time.time()
        logger.info('{}--->spend：{}s'.format(f.__name__, round(e_time - s_time, 2)))
        return res

    return inner


@func_retry()
def request_url(url, session=None):
    """
    request url
    :param url: https://www
    :param session: requests.session
    :return: Response Object
    """
    if session is not None:
        resp = session.get(url, timeout=(60, 60))
    else:
        resp = requests.get(url, timeout=(60, 60))
    if resp.status_code != 200:
        raise RuntimeError("Get repo config failed:{}, error:{}".format(url, resp.status_code))
    return resp


def load_yaml(file_path, method="load"):
    """read yaml to yaml obj"""
    yaml_load_method = getattr(yaml, method)
    with open(file_path, "r", encoding="utf-8") as file:
        return yaml_load_method(file, Loader=yaml.FullLoader)


@calc_time
def parse_relationship_config(relationship):
    """
    parse the repo config from yaml
    :param relationship: the object of yaml about relationship content
    :return:
        {
            sig-label: {
                sig_name: "OM",
                files: {file: [(gittee_id, email), ]}
                repo:  {repo_name: [(gittee_id, email), ]}
            }
        }
    """
    logger.info("-" * 25 + "start to parse relationship config" + "-" * 25)
    relationship_dict = defaultdict(dict)
    for sig_info in relationship.get("sigs", []):
        sig_label = sig_info["sig_label"].lower()
        relationship_dict[sig_label]["sig_name"] = sig_info["name"].lower()
        file_dict, repo_dict = defaultdict(list), defaultdict(list)
        files = sig_info.get("files", [])
        for file in files:
            file_list = file["file"]
            owner_list = file["owner"]
            for f in file_list:
                file_dict[f].extend([(owner["gitee_id"], owner["email"]) for owner in owner_list])
        repos = sig_info.get("repos", [])
        for rep in repos:
            repo_list = rep["repo"]
            owner_list = rep["owner"]
            for r in repo_list:
                repo_dict[r.lower()].extend([(owner["gitee_id"], owner["email"]) for owner in owner_list])
        relationship_dict[sig_label]["files"] = file_dict
        relationship_dict[sig_label]["repo"] = repo_dict
    return relationship_dict


@calc_time
def get_pr_info():
    """request all pr"""
    pr_info_list = list()
    page = 0
    while True:
        url = Config.pr_info_url.format(Config.gitee_token, page)
        resp = request_url(url)
        json_data = resp.json()
        pr_info_list.extend(json_data)
        logger.info("find pr count:{}".format(len(json_data)))
        if len(json_data) < 100:
            break
        page += 1
    logger.info("all find pr count:{}".format(len(pr_info_list)))
    return pr_info_list


def fill_status(status, insert_string):
    """meger status into string"""
    if status == '待合入':
        status = insert_string
    else:
        status += '{}{}'.format(Config.char_split, insert_string)
    return status


def fomart_status(pr_info):
    """
    format status
    :param pr_info: dict, { draft: True, label: {name: ci_failed}}
    :return: string,待合入
    """
    draft = pr_info['draft']
    labels = [label["name"] for label in pr_info['labels']]
    status = '待合入'
    if draft:
        status = fill_status(status, '草稿')
    if 'opengauss-cla/yes' not in labels:
        status = fill_status(status, 'CLA认证失败')
    if 'ci-pipeline-failed' in labels:
        status = fill_status(status, '门禁检查失败')
    if not pr_info['mergeable']:
        status = fill_status(status, '存在冲突')
    if 'kind/wait_for_update' in labels:
        status = fill_status(status, '等待更新')
    return status


def count_duration(start_time):
    """
    count the duration from the create datatime of pr to now
    :param start_time: the days
    :return:
    """
    today = datetime.datetime.today()
    start_date = datetime.datetime.strptime(start_time, '%Y-%m-%dT%H:%M:%S+08:00')
    duration = str((today - start_date).days)
    if int(duration) < 0:
        duration = '0'
    return duration


def parse_pr_info(pr_info_list):
    """parse pr info"""
    pr_list = list()
    for pr_info in pr_info_list:
        pr_dict = dict()
        pr_dict["repo_full_name"] = pr_info["base"]["repo"]["full_name"]
        pr_dict["repo_name"] = pr_info["base"]["repo"]["name"]
        pr_dict["branch"] = pr_info["base"]["ref"]
        pr_dict["pr_diff"] = pr_info["diff_url"]
        html = pr_info["_links"]["html"]["href"]
        # number link
        number = '#{}'.format(pr_info["number"])
        pr_dict["number_link"] = "<a href='{0}'>{1}</a>".format(html, number)
        # title
        pr_dict["pr_link"] = "<a href='{0}'>{1}</a>".format(html, pr_info["title"])
        # duration
        pr_dict["duration"] = count_duration(pr_info['created_at'])
        # status
        pr_dict["status"] = fomart_status(pr_info)
        # label
        pr_dict["label"] = [label["name"] for label in pr_info["labels"] if label["name"].startswith("sig/")]
        pr_list.append(pr_dict)
    return pr_list


def parse_pr_diff_info(repo_name, content):
    """parse pr path in pr.diff"""
    line_list = re.findall(r"diff --git (.*?)\\n", str(content))
    path_set = set()
    for line in line_list:
        list_content = line.split(r" ")
        path = repo_name + list_content[-1][1:]
        path_set.add(path)
    return list(path_set)


def parse_owner_pr_info(relationship_dict, pr_list):
    """
    parse owner pr info
    :param relationship_dict:
    {
        sig-label: {
            sig_name: "OM",
            files: {file: [(gittee_id, email), ]}
            repo:  {repo_name: [(gittee_id, email), ]}
            detail:  [(gitee_id, email), (gitee_id, email), (gitee_id, email)]
        }
    }
    :param pr_list:
    :return:
    """
    owner_repo_dict = defaultdict(list)
    user_email_dict = defaultdict(list)
    for index, pr in enumerate(pr_list):
        logger.info("{}:start to req:{}".format(str(index), pr["pr_diff"]))
        try:
            pr_diff = pr["pr_diff"]
            pr_labels = pr["label"]
            pr_repo_name = pr["repo_name"]
            if len(pr_labels) != 1:
                logger.error("There find invalid label amount in pr:{}".format(pr_diff))
                continue
            if pr_labels[0] not in relationship_dict.keys():
                logger.error("There find invalid label in pr:{}".format(pr_diff))
                continue
            pr_label = pr_labels[0]
            resp = request_url(pr_diff)
            path_list = parse_pr_diff_info(pr_repo_name, resp.content)
            files_dict = relationship_dict[pr_label]["files"]
            repo_dict = relationship_dict[pr_label]["repo"]
            detail_list = relationship_dict[pr_label]["detail"]
            is_in_path = False
            for path in path_list:
                if path in files_dict.keys():
                    for gitee_name, email in files_dict[path]:
                        owner_repo_dict[gitee_name].append(pr)
                        user_email_dict[gitee_name].append(email)
                        is_in_path = True
            if not is_in_path and pr_repo_name.lower() in repo_dict.keys():
                for gitee_name, email in repo_dict[pr_repo_name.lower()]:
                    owner_repo_dict[gitee_name].append(pr)
                    user_email_dict[gitee_name].append(email)
            for gitee_name, email in detail_list:
                owner_repo_dict[gitee_name].append(pr)
                user_email_dict[gitee_name].append(email)
        except requests.RequestException as e:
            logger.error("pr:{}, err:{}, traceback:{}".format(str(pr), e, traceback.format_exc()))
    return owner_repo_dict, user_email_dict


def pandas_clean(pr_info_list):
    """clean the data"""
    list_data, exist_pr = list(), list()
    for pr_info_temp in pr_info_list:
        if pr_info_temp["pr_diff"] not in exist_pr:
            dict_data = dict()
            dict_data["仓库"] = pr_info_temp["repo_full_name"]
            dict_data["目标分支"] = pr_info_temp["branch"]
            dict_data["编号"] = pr_info_temp["number_link"]
            dict_data["标题"] = pr_info_temp["pr_link"]
            dict_data["状态"] = pr_info_temp["status"]
            dict_data["开启天数"] = pr_info_temp["duration"]
            list_data.append(dict_data)
            exist_pr.append(pr_info_temp["pr_diff"])
    sort_list = sorted(list_data, key=lambda x: (x["仓库"], int(x["开启天数"])), reverse=True)
    for pr_info_temp in sort_list:
        status = pr_info_temp["状态"]
        color = status_color_positive_green(status)
        pr_info_temp["状态"] = '<font style="{}">{}</font>'.format(color, status)
        duration = pr_info_temp["开启天数"]
        color = duration_color_positive_green(duration)
        pr_info_temp["开启天数"] = '<font style="{}">{}</font>'.format(color, duration)
    return sort_list


@calc_time
def owner_repo_info(relationship_dict):
    """parse pr info"""
    logger.info("-" * 25 + "start to parse pr infor" + "-" * 25)
    pr_info_list = get_pr_info()
    pr_list = parse_pr_info(pr_info_list)
    return parse_owner_pr_info(relationship_dict, pr_list)


def status_color_positive_green(val):
    status_char_split = Config.char_split
    try:
        if status_char_split in val:
            val_list = val.split(status_char_split)
        else:
            val_list = [val]
        if "存在冲突" in val_list:
            color = "#FFFF00"
        elif "CLA认证失败" in val_list:
            color = "#FFFF00"
        elif "门禁检查失败" in val_list:
            color = "#FFFF00"
        elif "等待更新" in val_list:
            color = "#FFFF00"
        elif "草稿" in val_list:
            color = "#FFFF00"
        else:
            color = "white"
    except (TypeError, ValueError):
        color = 'red'
    return 'background-color:%s' % color


def duration_color_positive_green(val):
    value = int(val)
    try:
        if 7 < value <= 30:
            color = '#FFDAB9'
        elif 30 < value <= 365:
            color = '#FF7F50'
        elif value > 365:
            color = '#FF4500'
        else:
            color = "white"
    except (TypeError, ValueError):
        color = 'red'
    return 'background-color:%s' % color


def parse_owner_info(owner_content):
    """parse maintainer and committer from content"""
    owner_list = list()
    for content in owner_content.split("\n"):
        if content.startswith(r"-"):
            owner = re.findall(r"\((.*?)\)", content)
            email = re.findall(r"\*(.*?)\*", content)
            if owner and email:
                owner = owner[0].split(r"/")[-1]
                owner_list.append((owner, email[0]))
            else:
                logger.info("parse_owner_info match not find msg:{}".format(content))
    return owner_list


def parse_repo_info(repo_content):
    """parse repo from content"""
    repo_list = list()
    for content in repo_content.split("\n"):
        if content.startswith(r"-"):
            repo_name = content.split(r"/")[-1]
            repo_list.append(repo_name.lower())
    return repo_list


def parse_sig_info(readme_file_path_list):
    """
    parse the tc object,get the dict data
    :param readme_file_path_list: list, [path1, path2, path3]
    :return: dict, {sig-name: [(gitee_id, email), (gitee_id, email), (gitee_id, email)]}
    """
    sig_dict = defaultdict(list)
    for readme_file_path in readme_file_path_list:
        owner_list = list()
        with open(readme_file_path, "r", encoding="utf-8") as f:
            content = f.read()
        content = content.split("Maintainer列表")
        content = content[-1].split("Committer列表")
        maintainers = content[0]
        content = content[-1].split("联系方式")
        committer = content[0]
        maintainers_list = parse_owner_info(maintainers)
        owner_list.extend(maintainers_list)
        committer_list = parse_owner_info(committer)
        owner_list.extend(committer_list)
        sig_name = readme_file_path.split(r"/")[-2]
        if not owner_list or not sig_name:
            logger.info("parse_sig_info find empty info, and path is:{}".format(readme_file_path))
            continue
        sig_dict[sig_name.lower()] = owner_list
    return sig_dict


@calc_time
@func_retry()
def clone_object():
    """clone the tc object"""
    logger.info("-" * 25 + "start to clone tc rep" + "-" * 25)
    if os.path.exists(Config.clone_dir):
        shutil.rmtree(Config.clone_dir)
    ret, out, err = execute_cmd(Config.clone_cmd)
    if ret != 0:
        raise RuntimeError("clone object failed, err:{}".format(err))
    readme_file_path_list = list()
    for dir_path, _, filenames in os.walk(Config.clone_dir):
        if ".gitee" in dir_path:
            continue
        for filename in filenames:
            if filename == "README.md":
                abs_path = os.path.join(dir_path, filename)
                if "sigs/Template/README.md" in abs_path:
                    continue
                readme_file_path_list.append(abs_path)
    logger.info("-" * 25 + "start to parse tc rep" + "-" * 25)
    # read maintainers and committer from tc sigs
    sig_dict = parse_sig_info(readme_file_path_list)
    # read guass_relationship
    relationship = load_yaml(Config.gauss_relationship_path)
    if os.path.exists(Config.clone_dir):
        shutil.rmtree(Config.clone_dir)
    return sig_dict, relationship


# noinspection PyTypeChecker
@calc_time
def send_email(owner_repo_dict, user_email_dict):
    """send email"""
    logger.info("-" * 25 + "start to send email" + "-" * 25)
    pd.set_option('display.width', 800)
    pd.set_option('colheader_justify', 'center')
    pd.options.display.html.border = 2
    for gitee_name, pr_info_list in owner_repo_dict.items():
        gitee_email = list(set(user_email_dict[gitee_name]))
        new_pr_info = pandas_clean(pr_info_list)
        df = pd.DataFrame.from_dict(new_pr_info)
        # df_style = df.style.applymap(status_color_positive_green, subset=["状态"])
        # df_style = df_style.applymap(duration_color_positive_green, subset=["开启天数"])
        df_style = df.style.hide_index()
        html = df_style.render()
        content = div_template.format(gitee_name, html)
        template_content = html_template.replace(r"{{template}}", content)
        # it is for test
        if Config.debug:
            if not os.path.exists("file"):
                os.mkdir("file")
            with open("file/{}.html".format(gitee_name), "w+", encoding="utf-8") as f:
                f.write(template_content)
        email_impl = EmailImplement()
        email_impl.send_email(gitee_email, template_content)


def merge_sig_dict(sig_dict, relationship_dict):
    """

    :param sig_dict:
    {sig-name: [(gitee_id, email), (gitee_id, email), (gitee_id, email)]}
    :param relationship_dict:
    {
        sig-label: {
            sig_name: "OM",
            files: {file: [(gittee_id, email), ]}
            repo:  {repo_name: [(gittee_id, email), ]}
        }
    }
    :return:
    """
    for sig_label, sig_info in relationship_dict.items():
        if sig_info["sig_name"] in sig_dict.keys():
            relationship_dict[sig_label]["detail"] = sig_dict[sig_info["sig_name"]]


@calc_time
def main():
    """
    1. get config from https://gitee.com/opengauss/tc/blob/master/gauss_relationship.yaml, and parse it.
    2. get all open pr by requsting gitee, and parse it.
    3. send email to owner.
    :return: None
    """
    sig_dict, relationship = clone_object()
    relationship_dict = parse_relationship_config(relationship)
    merge_sig_dict(sig_dict, relationship_dict)
    owner_repo_dict, user_email_dict = owner_repo_info(relationship_dict)
    send_email(owner_repo_dict, user_email_dict)


if __name__ == '__main__':
    main()
