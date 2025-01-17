import datetime
from unittest import mock

import pytest
from django.test import override_settings
from django.utils import timezone

from .....checkout.error_codes import CheckoutErrorCode
from .....checkout.fetch import fetch_checkout_info, fetch_checkout_lines
from .....checkout.models import Checkout
from .....checkout.utils import add_variant_to_checkout
from .....plugins.base_plugin import ExcludedShippingMethod
from .....plugins.manager import get_plugins_manager
from .....warehouse.models import Reservation, Stock
from ....core.utils import to_global_id_or_none
from ....tests.utils import get_graphql_content
from ...mutations.utils import update_checkout_shipping_method_if_invalid

MUTATION_CHECKOUT_SHIPPING_ADDRESS_UPDATE = """
    mutation checkoutShippingAddressUpdate(
            $id: ID,
            $shippingAddress: AddressInput!,
        ) {
        checkoutShippingAddressUpdate(
                id: $id,
                shippingAddress: $shippingAddress,
        ) {
            checkout {
                token
                id
                shippingMethods{
                    id
                    name
                }
            }
            errors {
                field
                message
                code
            }
        }
    }"""


@mock.patch(
    "saleor.graphql.checkout.mutations.checkout_shipping_address_update."
    "update_checkout_shipping_method_if_invalid",
    wraps=update_checkout_shipping_method_if_invalid,
)
def test_checkout_shipping_address_update(
    mocked_update_shipping_method,
    user_api_client,
    checkout_with_item,
    graphql_address_data,
):
    checkout = checkout_with_item
    assert checkout.shipping_address is None
    previous_last_change = checkout.last_change

    shipping_address = graphql_address_data
    variables = {
        "id": to_global_id_or_none(checkout_with_item),
        "shippingAddress": shipping_address,
    }

    response = user_api_client.post_graphql(
        MUTATION_CHECKOUT_SHIPPING_ADDRESS_UPDATE, variables
    )
    content = get_graphql_content(response)
    data = content["data"]["checkoutShippingAddressUpdate"]
    assert not data["errors"]
    checkout.refresh_from_db()
    assert checkout.shipping_address is not None
    assert checkout.shipping_address.first_name == shipping_address["firstName"]
    assert checkout.shipping_address.last_name == shipping_address["lastName"]
    assert (
        checkout.shipping_address.street_address_1 == shipping_address["streetAddress1"]
    )
    assert (
        checkout.shipping_address.street_address_2 == shipping_address["streetAddress2"]
    )
    assert checkout.shipping_address.postal_code == shipping_address["postalCode"]
    assert checkout.shipping_address.country == shipping_address["country"]
    assert checkout.shipping_address.city == shipping_address["city"].upper()
    manager = get_plugins_manager()
    lines, _ = fetch_checkout_lines(checkout)
    checkout_info = fetch_checkout_info(checkout, lines, [], manager)
    mocked_update_shipping_method.assert_called_once_with(checkout_info, lines)
    assert checkout.last_change != previous_last_change


@mock.patch(
    "saleor.graphql.checkout.mutations.checkout_shipping_address_update."
    "update_checkout_shipping_method_if_invalid",
    wraps=update_checkout_shipping_method_if_invalid,
)
@override_settings(DEFAULT_COUNTRY="DE")
def test_checkout_shipping_address_update_changes_checkout_country(
    mocked_update_shipping_method,
    user_api_client,
    channel_USD,
    variant_with_many_stocks_different_shipping_zones,
    graphql_address_data,
):
    variant = variant_with_many_stocks_different_shipping_zones
    checkout = Checkout.objects.create(channel=channel_USD, currency="USD")
    checkout.set_country("PL", commit=True)
    checkout_info = fetch_checkout_info(checkout, [], [], get_plugins_manager())
    add_variant_to_checkout(checkout_info, variant, 1)
    assert checkout.shipping_address is None
    previous_last_change = checkout.last_change

    shipping_address = graphql_address_data
    shipping_address["country"] = "US"
    shipping_address["countryArea"] = "New York"
    shipping_address["postalCode"] = "10001"
    variables = {
        "id": to_global_id_or_none(checkout),
        "shippingAddress": shipping_address,
    }

    response = user_api_client.post_graphql(
        MUTATION_CHECKOUT_SHIPPING_ADDRESS_UPDATE, variables
    )
    content = get_graphql_content(response)
    data = content["data"]["checkoutShippingAddressUpdate"]
    assert not data["errors"]
    checkout.refresh_from_db()
    assert checkout.shipping_address is not None
    assert checkout.shipping_address.first_name == shipping_address["firstName"]
    assert checkout.shipping_address.last_name == shipping_address["lastName"]
    assert (
        checkout.shipping_address.street_address_1 == shipping_address["streetAddress1"]
    )
    assert (
        checkout.shipping_address.street_address_2 == shipping_address["streetAddress2"]
    )
    assert checkout.shipping_address.postal_code == shipping_address["postalCode"]
    assert checkout.shipping_address.country == shipping_address["country"]
    assert checkout.shipping_address.city == shipping_address["city"].upper()
    manager = get_plugins_manager()
    lines, _ = fetch_checkout_lines(checkout)
    checkout_info = fetch_checkout_info(checkout, lines, [], manager)
    mocked_update_shipping_method.assert_called_once_with(checkout_info, lines)
    assert checkout.country == shipping_address["country"]
    assert checkout.last_change != previous_last_change


@mock.patch(
    "saleor.graphql.checkout.mutations.checkout_shipping_address_update."
    "update_checkout_shipping_method_if_invalid",
    wraps=update_checkout_shipping_method_if_invalid,
)
@override_settings(DEFAULT_COUNTRY="DE")
def test_checkout_shipping_address_update_insufficient_stocks(
    mocked_update_shipping_method,
    channel_USD,
    user_api_client,
    variant_with_many_stocks_different_shipping_zones,
    graphql_address_data,
):
    variant = variant_with_many_stocks_different_shipping_zones
    checkout = Checkout.objects.create(channel=channel_USD, currency="USD")
    checkout.set_country("PL", commit=True)
    checkout_info = fetch_checkout_info(checkout, [], [], get_plugins_manager())
    add_variant_to_checkout(checkout_info, variant, 1)
    Stock.objects.filter(
        warehouse__shipping_zones__countries__contains="US", product_variant=variant
    ).update(quantity=0)
    assert checkout.shipping_address is None
    previous_last_change = checkout.last_change

    shipping_address = graphql_address_data
    shipping_address["country"] = "US"
    shipping_address["countryArea"] = "New York"
    shipping_address["postalCode"] = "10001"
    variables = {
        "id": to_global_id_or_none(checkout),
        "shippingAddress": shipping_address,
    }

    response = user_api_client.post_graphql(
        MUTATION_CHECKOUT_SHIPPING_ADDRESS_UPDATE, variables
    )
    content = get_graphql_content(response)
    data = content["data"]["checkoutShippingAddressUpdate"]
    errors = data["errors"]
    assert errors[0]["code"] == CheckoutErrorCode.INSUFFICIENT_STOCK.name
    assert errors[0]["field"] == "quantity"
    checkout.refresh_from_db()
    assert checkout.last_change == previous_last_change


@mock.patch(
    "saleor.graphql.checkout.mutations.checkout_shipping_address_update."
    "update_checkout_shipping_method_if_invalid",
    wraps=update_checkout_shipping_method_if_invalid,
)
@override_settings(DEFAULT_COUNTRY="DE")
def test_checkout_shipping_address_update_with_reserved_stocks(
    mocked_update_shipping_method,
    site_settings_with_reservations,
    channel_USD,
    user_api_client,
    variant_with_many_stocks_different_shipping_zones,
    graphql_address_data,
):
    variant = variant_with_many_stocks_different_shipping_zones
    checkout = Checkout.objects.create(channel=channel_USD, currency="USD")
    checkout.set_country("PL", commit=True)
    checkout_info = fetch_checkout_info(checkout, [], [], get_plugins_manager())
    add_variant_to_checkout(checkout_info, variant, 2)
    assert checkout.shipping_address is None

    shipping_address = graphql_address_data
    shipping_address["country"] = "US"
    shipping_address["countryArea"] = "New York"
    shipping_address["postalCode"] = "10001"
    variables = {
        "id": to_global_id_or_none(checkout),
        "shippingAddress": shipping_address,
    }
    other_checkout = Checkout.objects.create(channel=channel_USD, currency="USD")
    other_checkout_line = other_checkout.lines.create(
        variant=variant,
        quantity=1,
    )
    Reservation.objects.create(
        checkout_line=other_checkout_line,
        stock=variant.stocks.filter(
            warehouse__shipping_zones__countries__contains="US"
        ).first(),
        quantity_reserved=1,
        reserved_until=timezone.now() + datetime.timedelta(minutes=5),
    )

    response = user_api_client.post_graphql(
        MUTATION_CHECKOUT_SHIPPING_ADDRESS_UPDATE, variables
    )
    content = get_graphql_content(response)
    data = content["data"]["checkoutShippingAddressUpdate"]
    assert not data["errors"]


@mock.patch(
    "saleor.graphql.checkout.mutations.checkout_shipping_address_update."
    "update_checkout_shipping_method_if_invalid",
    wraps=update_checkout_shipping_method_if_invalid,
)
@override_settings(DEFAULT_COUNTRY="DE")
def test_checkout_shipping_address_update_against_reserved_stocks(
    mocked_update_shipping_method,
    site_settings_with_reservations,
    channel_USD,
    user_api_client,
    variant_with_many_stocks_different_shipping_zones,
    graphql_address_data,
):
    variant = variant_with_many_stocks_different_shipping_zones
    checkout = Checkout.objects.create(channel=channel_USD, currency="USD")
    checkout.set_country("PL", commit=True)
    checkout_info = fetch_checkout_info(checkout, [], [], get_plugins_manager())
    add_variant_to_checkout(checkout_info, variant, 2)
    Stock.objects.filter(
        warehouse__shipping_zones__countries__contains="US", product_variant=variant
    ).update(quantity=2)
    assert checkout.shipping_address is None

    shipping_address = graphql_address_data
    shipping_address["country"] = "US"
    shipping_address["countryArea"] = "New York"
    shipping_address["postalCode"] = "10001"
    variables = {
        "id": to_global_id_or_none(checkout),
        "shippingAddress": shipping_address,
    }

    other_checkout = Checkout.objects.create(channel=channel_USD, currency="USD")
    other_checkout_line = other_checkout.lines.create(
        variant=variant,
        quantity=3,
    )
    Reservation.objects.create(
        checkout_line=other_checkout_line,
        stock=variant.stocks.filter(
            warehouse__shipping_zones__countries__contains="US"
        ).first(),
        quantity_reserved=3,
        reserved_until=timezone.now() + datetime.timedelta(minutes=5),
    )

    response = user_api_client.post_graphql(
        MUTATION_CHECKOUT_SHIPPING_ADDRESS_UPDATE, variables
    )
    content = get_graphql_content(response)
    data = content["data"]["checkoutShippingAddressUpdate"]
    errors = data["errors"]
    assert errors[0]["code"] == CheckoutErrorCode.INSUFFICIENT_STOCK.name
    assert errors[0]["field"] == "quantity"


def test_checkout_shipping_address_update_channel_without_shipping_zones(
    user_api_client,
    checkout_with_item,
    graphql_address_data,
):
    checkout = checkout_with_item
    checkout.channel.shipping_zones.clear()
    assert checkout.shipping_address is None
    previous_last_change = checkout.last_change

    shipping_address = graphql_address_data
    variables = {
        "id": to_global_id_or_none(checkout),
        "shippingAddress": shipping_address,
    }

    response = user_api_client.post_graphql(
        MUTATION_CHECKOUT_SHIPPING_ADDRESS_UPDATE, variables
    )
    content = get_graphql_content(response)
    data = content["data"]["checkoutShippingAddressUpdate"]
    errors = data["errors"]
    assert errors[0]["code"] == CheckoutErrorCode.INSUFFICIENT_STOCK.name
    assert errors[0]["field"] == "quantity"
    checkout.refresh_from_db()
    assert checkout.last_change == previous_last_change


def test_checkout_shipping_address_with_invalid_phone_number_returns_error(
    user_api_client, checkout_with_item, graphql_address_data
):
    checkout = checkout_with_item
    assert checkout.shipping_address is None

    shipping_address = graphql_address_data
    shipping_address["phone"] = "+33600000"

    response = get_graphql_content(
        user_api_client.post_graphql(
            MUTATION_CHECKOUT_SHIPPING_ADDRESS_UPDATE,
            {
                "id": to_global_id_or_none(checkout),
                "shippingAddress": shipping_address,
            },
        )
    )["data"]["checkoutShippingAddressUpdate"]

    assert response["errors"] == [
        {
            "field": "phone",
            "message": "'+33600000' is not a valid phone number.",
            "code": CheckoutErrorCode.INVALID.name,
        }
    ]


@pytest.mark.parametrize(
    "number", ["+48321321888", "+44 (113) 892-1113", "00 44 (0) 20 7839 1377"]
)
def test_checkout_shipping_address_update_with_phone_country_prefix(
    number, user_api_client, checkout_with_item, graphql_address_data
):
    checkout = checkout_with_item
    assert checkout.shipping_address is None

    shipping_address = graphql_address_data
    shipping_address["phone"] = number
    variables = {
        "id": to_global_id_or_none(checkout),
        "shippingAddress": shipping_address,
    }

    response = user_api_client.post_graphql(
        MUTATION_CHECKOUT_SHIPPING_ADDRESS_UPDATE, variables
    )
    content = get_graphql_content(response)
    data = content["data"]["checkoutShippingAddressUpdate"]
    assert not data["errors"]


def test_checkout_shipping_address_update_without_phone_country_prefix(
    user_api_client, checkout_with_item, graphql_address_data
):
    checkout = checkout_with_item
    assert checkout.shipping_address is None

    shipping_address = graphql_address_data
    shipping_address["phone"] = "+1-202-555-0132"
    variables = {
        "id": to_global_id_or_none(checkout),
        "shippingAddress": shipping_address,
    }

    response = user_api_client.post_graphql(
        MUTATION_CHECKOUT_SHIPPING_ADDRESS_UPDATE, variables
    )
    content = get_graphql_content(response)
    data = content["data"]["checkoutShippingAddressUpdate"]
    assert not data["errors"]


@mock.patch(
    "saleor.plugins.manager.PluginsManager.excluded_shipping_methods_for_checkout"
)
def test_checkout_shipping_address_update_exclude_shipping_method(
    mocked_webhook,
    user_api_client,
    checkout_with_items_and_shipping,
    graphql_address_data,
    settings,
):
    settings.PLUGINS = ["saleor.plugins.webhook.plugin.WebhookPlugin"]
    checkout = checkout_with_items_and_shipping
    shipping_method = checkout.shipping_method
    assert shipping_method is not None
    webhook_reason = "hello-there"
    mocked_webhook.return_value = [
        ExcludedShippingMethod(shipping_method.id, webhook_reason)
    ]
    shipping_address = graphql_address_data
    variables = {
        "id": to_global_id_or_none(checkout),
        "shippingAddress": shipping_address,
    }

    user_api_client.post_graphql(MUTATION_CHECKOUT_SHIPPING_ADDRESS_UPDATE, variables)
    checkout.refresh_from_db()
    assert checkout.shipping_method is None
