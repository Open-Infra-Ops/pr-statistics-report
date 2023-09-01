FROM openeuler/openeuler:22.03-lts-sp1

MAINTAINER TomNewChao<tom_toworld@163.com>

RUN mkdir -p /opt/crontab_issue_close

COPY . /opt/crontab_issue_close/

RUN yum update -y && yum install -y python3 python3-pip git

RUN pip3 install -r /opt/crontab_issue_close/requirements.txt

WORKDIR /opt/crontab_issue_close

ENTRYPOINT ["python3", "/opt/crontab_issue_close/crontab_issue_close.py"]