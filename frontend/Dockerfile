FROM httpd:alpine

# Enable more detailed access logs
RUN sed -i 's|LogFormat "%h %l %u %t \\"%r\\" %>s %b" common|LogFormat "%h %l %u %t \\"%r\\" %>s %b \\"%{Referer}i\\" \\"%{User-Agent}i\\" %T/%D" common|g' /usr/local/apache2/conf/httpd.conf

# Set error log level to debug for more details
RUN sed -i 's/LogLevel warn/LogLevel debug/g' /usr/local/apache2/conf/httpd.conf

# Change Apache default port to 8080
RUN sed -i 's/Listen 80/Listen 8080/g' /usr/local/apache2/conf/httpd.conf

# Enable proxy modules (needed for reverse-proxying API calls to backend containers)
RUN sed -i \
    -e 's/#LoadModule proxy_module/LoadModule proxy_module/' \
    -e 's/#LoadModule proxy_http_module/LoadModule proxy_http_module/' \
    -e 's/#LoadModule proxy_connect_module/LoadModule proxy_connect_module/' \
    -e 's/#LoadModule ssl_module/LoadModule ssl_module/' \
    -e 's/#LoadModule socache_shmcb_module/LoadModule socache_shmcb_module/' \
    -e 's/#LoadModule headers_module/LoadModule headers_module/' \
    -e 's/#LoadModule rewrite_module/LoadModule rewrite_module/' \
    /usr/local/apache2/conf/httpd.conf

# Append our proxy rules to the main httpd.conf
COPY frontend/httpd.conf /usr/local/apache2/conf/extra/proxy-rules.conf
RUN echo "Include conf/extra/proxy-rules.conf" >> /usr/local/apache2/conf/httpd.conf

COPY frontend/ /usr/local/apache2/htdocs/

EXPOSE 8080
