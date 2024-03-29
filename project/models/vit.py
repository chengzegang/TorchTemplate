from __future__ import annotations

from typing import Callable

import torch
import torch.distributed as dist
import torch.nn.functional as F
from torch import nn
from torch.nn.parameter import Parameter

from ..transforms import Normalize


class PatchEmbedding(nn.Module):
    def __init__(
        self, image_size: int, patch_size: int, hidden_size: int, **kwargs
    ) -> None:
        super().__init__()

        num_patches = (image_size // patch_size) ** 2

        self.patch_embedding = nn.Conv2d(
            3, hidden_size, kernel_size=patch_size, stride=patch_size, bias=False
        )

        self.positional_embedding = nn.Embedding(num_patches, hidden_size)
        positional_ids = torch.arange(num_patches).expand((1, -1))
        self.register_buffer("positional_ids", positional_ids)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        patch_embedds: torch.Tensor = (
            self.patch_embedding(x).flatten(2).transpose(-1, -2)
        )
        patch_embedds = patch_embedds + self.positional_embedding(
            self.positional_ids
        ).expand_as(patch_embedds)
        return patch_embedds  # type: ignore


class VisionTransformer(nn.Module):
    def __init__(
        self,
        image_size: int,
        patch_size: int,
        num_layers: int,
        num_heads: int,
        hidden_size: int,
        intermediate_size: int,
        dropout: float = 0.1,
        acitvate_fn: Callable[[torch.Tensor], torch.Tensor] = F.gelu,
        **kwargs,
    ) -> None:
        super().__init__()

        self.patch_embedding = PatchEmbedding(image_size, patch_size, hidden_size)
        self.layers = nn.TransformerEncoder(
            nn.TransformerEncoderLayer(
                hidden_size,
                num_heads,
                intermediate_size,
                dropout,
                acitvate_fn,
                batch_first=True,
            ),
            num_layers,
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        patch_embedds: torch.Tensor = self.patch_embedding(x)
        output_logits: torch.Tensor = self.layers(patch_embedds)

        return output_logits


class RectVit(nn.Module):
    def __init__(
        self,
        image_size: int,
        patch_size: int,
        num_encoder_layers: int,
        num_decoder_layers: int,
        num_heads: int,
        hidden_size: int,
        intermediate_size: int,
        dropout: float = 0.1,
        acitvate_fn: Callable[[torch.Tensor], torch.Tensor] = F.gelu,
        **kwargs,
    ) -> None:
        super().__init__()
        self.image_size = image_size
        self.patch_size = patch_size
        self.encoder = VisionTransformer(
            image_size,
            patch_size,
            num_encoder_layers,
            num_heads,
            hidden_size,
            intermediate_size,
            dropout,
            acitvate_fn,
        )
        self.decoder = nn.TransformerEncoder(
            nn.TransformerEncoderLayer(
                hidden_size,
                num_heads,
                intermediate_size,
                dropout,
                acitvate_fn,
                batch_first=True,
            ),
            num_decoder_layers,
        )
        self.projector = nn.Linear(hidden_size, patch_size**2 * 3)
        self.normalize = Normalize()

    def rect(self, x: torch.Tensor) -> torch.Tensor:
        x = x.transpose(-1, -2)
        x = F.fold(
            x,
            output_size=self.image_size,
            kernel_size=self.patch_size,
            stride=self.patch_size,
        )
        return x

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.normalize(x)
        x = self.encoder(x)
        x = self.decoder(x)
        x = self.projector(x)
        x = self.rect(x) * 255
        x = torch.clamp(x, 0, 255)
        return x


def build_vit(**kwargs) -> nn.Module:
    return RectVit(**kwargs)
