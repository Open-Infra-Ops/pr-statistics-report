FROM openeuler/openeuler:22.03
RUN python3 -m ensurepip --default-pip && python3 -m pip install --upgrade pip
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple
RUN pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn
RUN pip config set global.timeout 120

RUN mkdir -p /opt/pr-statistics

COPY . /opt/pr-statistics/

RUN yum update -y && yum install -y python3-pip git

RUN pip3 install -r /opt/pr-statistics/requirements.txt

WORKDIR /opt/pr-statistics

ENTRYPOINT ["python3", "/opt/pr-statistics/pr_statistics.py"]
