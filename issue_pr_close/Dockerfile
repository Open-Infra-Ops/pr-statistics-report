FROM openeuler/openeuler:22.03
RUN python3 -m ensurepip --default-pip && python3 -m pip install --upgrade pip
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
RUN pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn
RUN pip config set global.timeout 120

RUN mkdir -p /opt/crontab_issue_close

COPY . /opt/crontab_issue_close/

RUN yum update -y && yum install -y python3 python3-pip git

RUN pip3 install -r /opt/crontab_issue_close/requirements.txt

WORKDIR /opt/crontab_issue_close

RUN groupadd -g 1000 crontabissue
RUN useradd -u 1000 -g crontabissue -s /bin/sh -m crontabissue
RUN chown -R crontabissue:crontabissue /opt/crontab_issue_close
USER 1000:1000
ENTRYPOINT ["python3", "/opt/crontab_issue_close/crontab_issue_close.py"]