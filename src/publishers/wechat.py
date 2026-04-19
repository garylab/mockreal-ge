from __future__ import annotations

from loguru import logger as log

from src.publishers.base import BasePublisher, PublishResult
from src.storage.models import ContentPackage


class WechatPublisher(BasePublisher):
    """WeChat Official Account (公众号) publisher.

    Currently a stub — content is generated and saved to the DB
    (content.wechat_article) during the pipeline. Actual publishing
    via the WeChat MP API will be added later.
    """

    platform = "wechat"

    async def publish(self, pkg: ContentPackage, cta_variant: str = "A") -> PublishResult:
        if not pkg.wechat_article:
            return PublishResult(self.platform, "", False, "No wechat_article generated")

        log.info("WeChat article ready for '{}' ({} chars, saved to DB)",
                 pkg.article_title, len(pkg.wechat_article))
        return PublishResult(self.platform, "", False, "WeChat publishing not configured yet")
